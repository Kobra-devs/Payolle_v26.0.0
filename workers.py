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


def process_supplier_event(event: dict[str, Any], client=None) -> bool:
    client = client or redis_client.client
    product_id = event["id"]
    key = f"product:{product_id}"
    current = client.hgetall(key)
    if _is_stale(current, event):
        logger.info("Ignoring stale supplier event for %s", product_id)
        return False

    event_type = event["event_type"]
    if event_type == "product.deleted":
        categories = _categories(client, product_id, current, event)
        client.delete(key)
        for category in categories:
            client.srem(f"category:{category}", product_id)
        event["categories"] = sorted(categories)
    else:
        fields = dict(event.get("fields", {}))
        fields.update({field: event[field] for field in ("price", "inventory") if field in event})
        if event_type == "category.moved":
            categories = _categories(client, product_id, current, event)
            if event.get("old_category"):
                categories.discard(event["old_category"])
                client.srem(f"category:{event['old_category']}", product_id)
            categories.add(event["new_category"])
            client.sadd(f"category:{event['new_category']}", product_id)
            fields["categories"] = json.dumps(sorted(categories))
        elif event_type == "product.created":
            categories = set(fields.get("categories", [])) if isinstance(fields.get("categories"), list) else set()
            for category in categories:
                client.sadd(f"category:{category}", product_id)
            if categories:
                fields["categories"] = json.dumps(sorted(categories))
            event["categories"] = sorted(categories)
        fields.update({field: event[field] for field in ("version", "updated_at") if field in event})
        fields["id"] = product_id
        if fields:
            client.hset(key, mapping=fields)

    client.publish(Config.REDIS_UPDATES_CHANNEL, json.dumps(event))
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
        if queue == Config.REDIS_PRIORITY_QUEUE:
            process_supplier_event(json.loads(payload), client)
        else:
            process_bulk_task(json.loads(payload), client)
