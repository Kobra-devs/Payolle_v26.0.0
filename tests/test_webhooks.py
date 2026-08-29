import hashlib
import hmac
import json

import pytest

from transformers import transform_event
from workers import process_supplier_event


SECRET = "mock-supplier-webhook-secret"


class FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.sets = {}
        self.published = []
        self.queued = []

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def hset(self, key, mapping=None, *args):
        if mapping is None:
            mapping = {args[0]: args[1]}
        self.hashes.setdefault(key, {}).update({str(k): str(v) for k, v in mapping.items()})

    def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)

    def srem(self, key, value):
        self.sets.setdefault(key, set()).discard(value)

    def delete(self, key):
        self.hashes.pop(key, None)

    def publish(self, channel, payload):
        self.published.append((channel, json.loads(payload)))


def test_transformer_supports_all_supplier_events():
    assert transform_event({"event_type": "price.changed", "data": {"id": "p1", "price": 4}})["price"] == 4
    assert transform_event({"event_type": "inventory.changed", "data": {"sku": "p1", "qty": 3}})["inventory"] == 3
    assert transform_event({"event_type": "metadata.changed", "data": {"id": "p1", "fields": {"name": "New"}}})["fields"] == {"name": "New"}
    assert transform_event({"event_type": "category.moved", "data": {"id": "p1", "from": "old", "to": "new"}})["new_category"] == "new"
    assert transform_event({"event_type": "product.deleted", "data": {"id": "p1"}})["id"] == "p1"


def test_stale_events_are_ignored():
    client = FakeRedis()
    client.hashes["product:p1"] = {"id": "p1", "version": "4", "price": "10"}
    assert not process_supplier_event({"event_type": "price.changed", "id": "p1", "price": 5, "version": 3}, client)
    assert client.hashes["product:p1"]["price"] == "10"


def test_category_move_and_delete_update_sets_and_hash():
    client = FakeRedis()
    client.hashes["product:p1"] = {"id": "p1", "categories": '["old"]'}
    process_supplier_event({"event_type": "category.moved", "id": "p1", "old_category": "old", "new_category": "new", "version": 2}, client)
    assert "p1" not in client.sets.get("category:old", set())
    assert "p1" in client.sets["category:new"]
    process_supplier_event({"event_type": "product.deleted", "id": "p1", "categories": ["new"], "version": 3}, client)
    assert "product:p1" not in client.hashes
    assert "p1" not in client.sets["category:new"]


def test_delete_tombstone_rejects_late_create():
    client = FakeRedis()
    process_supplier_event({"event_type": "product.deleted", "id": "p1", "version": 5}, client)
    accepted = process_supplier_event(
        {"event_type": "product.created", "id": "p1", "version": 4, "fields": {"name": "Late", "categories": ["default"]}},
        client,
    )
    assert not accepted
    assert "product:p1" not in client.hashes
    assert client.published[-1][1]["telemetry"] == "event_rejected"
    assert client.published[-1][1]["reason"] == "tombstone_active"
