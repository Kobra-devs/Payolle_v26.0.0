import xml.etree.ElementTree as ET
from typing import Any


def parse_xml(content: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(content)
    if root.tag != "products":
        raise ValueError("XML root must be <products>")
    products = []
    for product in root.findall("product"):
        def text(path: str) -> str | None:
            node = product.find(path)
            return node.text.strip() if node is not None and node.text else None

        products.append({
            "id": product.get("id") or text("id"),
            "name": product.get("title") or text("title") or text("name"),
            "price": text("price"),
            "qty": text("qty") or text("inventory") or "0",
        })
    return products
