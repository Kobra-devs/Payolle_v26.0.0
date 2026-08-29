import json

from parsers.csv_parser import parse_csv
from parsers.jsonld_parser import parse_jsonld
from parsers.xml_parser import parse_xml
from services.normalizer import normalize_product


def test_csv_normalizes_product():
    rows = parse_csv(b"id,title,price,qty\nabc,Widget,12.50,4\n")
    product = normalize_product(rows[0])
    assert product["id"] == "abc"
    assert product["price"] == 12.5
    assert product["inventory"] == 4


def test_jsonld_parses_schema_product():
    rows = parse_jsonld(json.loads(b'{"@type":"Product","sku":"x1","name":"X","offers":{"price":3}}'))
    assert rows == [{"id": "x1", "name": "X", "price": 3, "qty": 0}]


def test_xml_parses_nested_product():
    rows = parse_xml(b"<products><product><id>x2</id><name>Y</name><price>4.5</price><inventory>2</inventory></product></products>")
    assert rows[0]["id"] == "x2"
    assert rows[0]["qty"] == "2"
