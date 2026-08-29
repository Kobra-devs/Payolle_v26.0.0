from typing import Any


def parse_jsonld(payload: Any) -> list[dict[str, Any]]:
    items = payload if isinstance(payload, list) else [payload]
    products = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("JSON-LD product must be an object")
        if item.get("@type") not in (None, "Product") and "Product" not in item.get("@type", []):
            continue
        offers = item.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        products.append({
            "id": item.get("sku") or item.get("productID") or item.get("@id"),
            "name": item.get("name"),
            "price": offers.get("price") if isinstance(offers, dict) else None,
            "qty": item.get("inventoryLevel") or item.get("quantity") or 0,
        })
    return products
