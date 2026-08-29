from datetime import datetime, timezone
from typing import Any


def normalize_product(raw: dict[str, Any]) -> dict[str, Any]:
    product_id = raw.get("id")
    name = raw.get("name")
    if product_id is None or name is None or str(product_id).strip() == "" or str(name).strip() == "":
        raise ValueError("Product requires id and name")
    try:
        price = float(raw.get("price"))
        inventory = int(float(raw.get("qty", 0)))
    except (TypeError, ValueError) as exc:
        raise ValueError("Product price must be numeric and qty must be an integer") from exc
    if price < 0 or inventory < 0:
        raise ValueError("Product price and inventory cannot be negative")
    return {
        "id": str(product_id).strip(),
        "name": str(name).strip(),
        "price": price,
        "inventory": inventory,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
