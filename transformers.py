"""Validation and normalization for supplier events."""

from __future__ import annotations

import math
from typing import Any

SUPPORTED_EVENTS = {
    "product.created",
    "price.changed",
    "inventory.changed",
    "metadata.changed",
    "category.moved",
    "product.deleted",
}


def _details(payload: dict[str, Any]) -> dict[str, Any]:
    details = payload.get("data") or payload.get("product") or payload
    if not isinstance(details, dict):
        raise ValueError("event data must be an object")
    return details


def transform_event(payload: dict[str, Any]) -> dict[str, Any]:
    event_type = payload.get("event_type")
    if event_type not in SUPPORTED_EVENTS:
        raise ValueError("unsupported event_type")

    details = _details(payload)
    product_id = details.get("id", details.get("product_id", details.get("sku")))
    if product_id is None or not str(product_id).strip():
        raise ValueError("event must include a product id")

    event = {
        "event_type": event_type,
        "id": str(product_id).strip(),
    }
    for key in ("version", "updated_at", "source_timestamp"):
        if key in payload:
            event[key] = payload[key]
        elif key in details:
            event[key] = details[key]

    if event_type in {"product.created", "metadata.changed"}:
        fields = details.get("fields", details)
        if not isinstance(fields, dict):
            raise ValueError("event fields must be an object")
        event["fields"] = {
            key: value
            for key, value in fields.items()
            if key not in {"id", "product_id", "sku", "event_type", "data", "product", "version", "updated_at", "source_timestamp"}
        }
        if isinstance(event["fields"].get("categories"), str):
            event["fields"]["categories"] = [event["fields"]["categories"]]
        if event_type == "product.created" and not event["fields"].get("name"):
            raise ValueError("product.created must include name")
    elif event_type in {"price.changed", "inventory.changed"}:
        field = "price" if event_type == "price.changed" else "inventory"
        value = details.get(field, details.get("qty") if field == "inventory" else None)
        try:
            numeric_value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be numeric") from exc
        if not math.isfinite(numeric_value) or numeric_value < 0:
            raise ValueError(f"{field} must be a non-negative finite number")
        if field == "inventory" and numeric_value != int(numeric_value):
            raise ValueError("inventory must be an integer")
        event[field] = int(numeric_value) if field == "inventory" else numeric_value
    elif event_type == "category.moved":
        old_category = details.get("old_category", details.get("from"))
        new_category = details.get("new_category", details.get("to", details.get("category")))
        if not new_category or not str(new_category).strip():
            raise ValueError("category.moved must include a destination category")
        event["old_category"] = str(old_category).strip() if old_category else None
        event["new_category"] = str(new_category).strip()
    elif event_type == "product.deleted":
        categories = details.get("categories", [])
        if isinstance(categories, str):
            categories = [categories]
        if not isinstance(categories, list):
            raise ValueError("categories must be a list")
        event["categories"] = [str(category).strip() for category in categories if str(category).strip()]

    return event
