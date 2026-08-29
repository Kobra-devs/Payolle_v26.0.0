import json
from typing import Any

from parsers.csv_parser import parse_csv
from parsers.jsonld_parser import parse_jsonld
from parsers.xml_parser import parse_xml

PARSERS = {"jsonld": parse_jsonld, "csv": parse_csv, "xml": parse_xml}


def parse_catalog(content: bytes, file_format: str) -> list[dict[str, Any]]:
    try:
        if file_format == "jsonld":
            return PARSERS[file_format](json.loads(content.decode("utf-8")))
        return PARSERS[file_format](content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid {file_format} document") from exc
