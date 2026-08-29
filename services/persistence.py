import json

from extensions import redis_client


PRODUCT_UPDATES_CHANNEL = "product_updates"


def save_products(products: list[dict], channel: str = PRODUCT_UPDATES_CHANNEL) -> int:
    saved = 0
    for product in products:
        key = f"product:{product['id']}"
        redis_client.client.hset(key, mapping=product)
        redis_client.client.publish(channel, json.dumps(product))
        saved += 1
    return saved


def update_product_fields(product: dict, channel: str = PRODUCT_UPDATES_CHANNEL) -> None:
    """Persist and publish a validated partial product update."""
    key = f"product:{product['id']}"
    redis_client.client.hset(key, mapping=product)
    redis_client.client.publish(channel, json.dumps(product))
