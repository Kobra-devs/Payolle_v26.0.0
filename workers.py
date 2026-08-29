"""Redis queue processors for bulk tasks and supplier events."""

from __future__ import annotations

import json
import logging
from typing import Any

from config import Config
from extensions import redis_client
from services.ingestion import parse_catalog
from services.normalizer import normalize_product
from services.persistence import save_products

logger = logging.getLogger(__name__)


def _telemetry(event: dict[str, Any], outcome: str, reason: str | None = None) -> dict[str, Any]:
    """Small, dashboard-oriented record kept separate from domain broadcasts."""
    payload = {
        "telemetry": outcome,
        "id": event["id"],
        "event_type": event["event_type"],
        "source_timestamp": event.get("source_timestamp", event.get("updated_at")),
    }
    if reason:
        payload["reason"] = reason
    return payload


def _publish_telemetry(client, event: dict[str, Any], outcome: str, reason: str | None = None) -> None:
    client.publish(Config.REDIS_UPDATES_CHANNEL, json.dumps(_telemetry(event, outcome, reason)))


def _decode_hash(values: dict[str, Any]) -> dict[str, Any]:
    """Turn Redis hash values into a JSON-friendly product snapshot."""
    decoded = dict(values)
    for field in ("price", "inventory", "version"):
        if field not in decoded:
            continue
        try:
            decoded[field] = float(decoded[field]) if field == "price" else int(decoded[field])
        except (TypeError, ValueError):
            pass
    if isinstance(decoded.get("categories"), str):
        try:
            decoded["categories"] = json.loads(decoded["categories"])
        except json.JSONDecodeError:
            decoded["categories"] = []
    return decoded


def _redis_fields(fields: dict[str, Any]) -> dict[str, str]:
    """Redis hashes only accept scalar values; serialize structured metadata."""
    return {
        str(key): json.dumps(value, separators=(",", ":")) if isinstance(value, (dict, list, bool, type(None))) else str(value)
        for key, value in fields.items()
    }


def _is_stale(current: dict[str, Any], event: dict[str, Any]) -> bool:
    if event.get("version") is not None and current.get("version") is not None:
        try:
            return int(event["version"]) <= int(current["version"])
        except (TypeError, ValueError):
            return str(event["version"]) <= str(current["version"])
    if event.get("updated_at") and current.get("updated_at"):
        return str(event["updated_at"]) <= str(current["updated_at"])
    return False


def _categories(client, product_id: str, current: dict[str, Any], event: dict[str, Any]) -> set[str]:
    categories = set(event.get("categories", []))
    try:
        categories.update(json.loads(current.get("categories", "[]")))
    except (TypeError, json.JSONDecodeError):
        pass
    return {str(category) for category in categories if category}


def _prepare_event(event: dict[str, Any], current: dict[str, Any]) -> tuple[dict[str, str], set[str], set[str]]:
    """Return hash writes, category-set removals, and category-set additions."""
    event_type = event["event_type"]
    existing_categories = _categories(None, event["id"], current, {"categories": []})
    supplied_categories = event.get("categories", [])

    if event_type == "product.deleted":
        categories = existing_categories | {str(value) for value in supplied_categories if value}
        event["categories"] = sorted(categories)
        event["product"] = _decode_hash(current)
        return {}, categories, set()

    fields = dict(event.get("fields", {}))
    fields.update({field: event[field] for field in ("price", "inventory") if field in event})
    fields.update({field: event[field] for field in ("version", "updated_at") if field in event})
    fields["id"] = event["id"]

    remove_categories: set[str] = set()
    add_categories: set[str] = set()
    if event_type == "product.created":
        categories = fields.get("categories", [])
        if not isinstance(categories, list):
            categories = [categories]
        add_categories = {str(value).strip() for value in categories if str(value).strip()}
        if add_categories:
            fields["categories"] = sorted(add_categories)
        event["categories"] = sorted(add_categories)
    elif event_type == "category.moved":
        old_category = event.get("old_category")
        if old_category:
            remove_categories.add(str(old_category))
        categories = existing_categories - remove_categories
        categories.add(str(event["new_category"]))
        add_categories.add(str(event["new_category"]))
        fields["categories"] = sorted(categories)
        # Both rooms must hear this lifecycle transition.
        event["categories"] = sorted(categories | remove_categories)
    elif "categories" in fields:
        categories = {str(value).strip() for value in fields["categories"] if str(value).strip()} if isinstance(fields["categories"], list) else set()
        remove_categories = existing_categories - categories
        add_categories = categories - existing_categories
        fields["categories"] = sorted(categories)

    return _redis_fields(fields), remove_categories, add_categories


def process_supplier_event(event: dict[str, Any], client=None) -> bool:
    client = client or redis_client.client
    product_id = event["id"]
    key = f"product:{product_id}"
    tombstone_key = f"product_tombstone:{product_id}"
    # WATCH makes the comparison and mutation one optimistic transaction.  This
    # is important when several queue workers receive supplier events at once.
    if not hasattr(client, "pipeline"):
        return _process_event_linear(event, client)

    import redis

    for _ in range(5):
        with client.pipeline() as pipe:
            try:
                pipe.watch(key, tombstone_key)
                current = pipe.hgetall(key)
                tombstone = pipe.hgetall(tombstone_key)
                # A tombstone keeps a late, older create/update from
                # resurrecting a product after its hash has been hard-deleted.
                state = current or tombstone
                if _is_stale(state, event):
                    pipe.unwatch()
                    reason = "tombstone_active" if tombstone and not current else "stale_timestamp"
                    _publish_telemetry(client, event, "event_rejected", reason)
                    logger.info("Rejected supplier event for %s: %s", product_id, reason)
                    return False
                fields, removals, additions = _prepare_event(event, current)
                pipe.multi()
                if event["event_type"] == "product.deleted":
                    pipe.delete(key)
                    tombstone_fields = {"deleted": "1"}
                    tombstone_fields.update({field: str(event[field]) for field in ("version", "updated_at") if field in event})
                    pipe.hset(tombstone_key, mapping=tombstone_fields)
                else:
                    pipe.hset(key, mapping=fields)
                    pipe.delete(tombstone_key)
                for category in removals:
                    pipe.srem(f"category:{category}", product_id)
                for category in additions:
                    pipe.sadd(f"category:{category}", product_id)
                if event["event_type"] != "product.deleted":
                    event["product"] = _decode_hash({**current, **fields})
                pipe.publish(Config.REDIS_UPDATES_CHANNEL, json.dumps(event))
                pipe.publish(Config.REDIS_UPDATES_CHANNEL, json.dumps(_telemetry(event, "event_processed")))
                pipe.execute()
                return True
            except redis.WatchError:
                continue
    raise RuntimeError(f"Could not commit supplier event for {product_id} after retries")


def _process_event_linear(event: dict[str, Any], client) -> bool:
    """Compatibility path for small Redis fakes used by unit tests."""
    product_id = event["id"]
    key = f"product:{product_id}"
    tombstone_key = f"product_tombstone:{product_id}"
    current = client.hgetall(key)
    tombstone = client.hgetall(tombstone_key)
    if _is_stale(current or tombstone, event):
        reason = "tombstone_active" if tombstone and not current else "stale_timestamp"
        _publish_telemetry(client, event, "event_rejected", reason)
        return False
    fields, removals, additions = _prepare_event(event, current)
    if event["event_type"] == "product.deleted":
        client.delete(key)
        tombstone_fields = {"deleted": "1"}
        tombstone_fields.update({field: str(event[field]) for field in ("version", "updated_at") if field in event})
        client.hset(tombstone_key, mapping=tombstone_fields)
    else:
        client.hset(key, mapping=fields)
        client.delete(tombstone_key)
        event["product"] = _decode_hash({**current, **fields})
    for category in removals:
        client.srem(f"category:{category}", product_id)
    for category in additions:
        client.sadd(f"category:{category}", product_id)
    client.publish(Config.REDIS_UPDATES_CHANNEL, json.dumps(event))
    _publish_telemetry(client, event, "event_processed")
    return True


def process_bulk_task(task: dict[str, Any], client) -> None:
    task_id = task["task_id"]
    task_key = f"ingest_task:{task_id}"
    try:
        client.hset(task_key, "status", "processing")
        raw_products = parse_catalog(task["content"].encode("utf-8"), task["format"])
        products = [normalize_product(product) for product in raw_products]
        saved = save_products(products, Config.REDIS_UPDATES_CHANNEL)
        client.hset(task_key, mapping={"status": "completed", "products_saved": saved})
    except Exception as exc:
        client.hset(task_key, mapping={"status": "failed", "error": str(exc)})
        logger.exception("Task %s failed", task_id)


def run_worker() -> None:
    import redis
    import signal

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    running = True

    def stop_worker(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop_worker)
    signal.signal(signal.SIGTERM, stop_worker)
    client = redis.Redis.from_url(Config.REDIS_URL, decode_responses=True)
    redis_client.client = client
    logger.info("Worker listening on %s and %s", Config.REDIS_PRIORITY_QUEUE, Config.REDIS_TASK_QUEUE)
    while running:
        result = client.blpop([Config.REDIS_PRIORITY_QUEUE, Config.REDIS_TASK_QUEUE], timeout=2)
        if not result:
            continue
        queue, payload = result
        try:
            if queue == Config.REDIS_PRIORITY_QUEUE:
                process_supplier_event(json.loads(payload), client)
            else:
                process_bulk_task(json.loads(payload), client)
        except (json.JSONDecodeError, KeyError, ValueError):
            logger.exception("Discarding malformed job from %s", queue)
