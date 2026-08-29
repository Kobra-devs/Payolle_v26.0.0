import csv
import io
from typing import Any

REQUIRED_HEADERS = {"id", "title", "price", "qty"}


def parse_csv(content: bytes) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    headers = set(reader.fieldnames or [])
    missing = REQUIRED_HEADERS - headers
    if missing:
        raise ValueError(f"CSV missing required headers: {', '.join(sorted(missing))}")
    return [
        {"id": row.get("id"), "name": row.get("title"), "price": row.get("price"), "qty": row.get("qty")}
        for row in reader
    ]
