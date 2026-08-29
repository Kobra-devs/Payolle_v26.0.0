"""Concurrent Faker supplier simulator for stressing the webhook ingestion path.

Example: python simulator.py --rate 150 --workers 24 --pool-size 20
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests
from faker import Faker


CATEGORIES = ["default", "featured", "coffee", "home", "electronics", "seasonal"]
EVENT_TYPES = ["product.created", "price.changed", "inventory.changed", "metadata.changed", "category.moved", "product.deleted"]


@dataclass
class SimulatedProduct:
    id: str
    categories: list[str] = field(default_factory=lambda: ["default"])
    version: int = 0
    deleted: bool = False


class SupplierSimulator:
    def __init__(self, args: argparse.Namespace):
        self.args, self.fake = args, Faker()
        self.products = [SimulatedProduct(id=f"sku-{self.fake.ean13()}") for _ in range(args.pool_size)]
        self.lock, self.sent, self.failed = threading.Lock(), 0, 0

    @staticmethod
    def timestamp() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _choose_event(self, product: SimulatedProduct) -> str:
        if product.deleted:
            # Most new-version creates legitimately revive a product; the rest
            # intentionally probe the tombstone rejection path.
            return random.choices(["product.created", "price.changed", "metadata.changed"], [75, 15, 10])[0]
        return random.choices(EVENT_TYPES, [12, 31, 26, 16, 9, 6])[0]

    def make_payload(self) -> dict:
        with self.lock:
            product = random.choice(self.products)
            event_type = self._choose_event(product)
            product.version += 1
            version = product.version
            # About one fifth of requests intentionally arrive behind a newer
            # version; concurrent execution also naturally reorders requests.
            if random.random() < self.args.stale_ratio and version > 1:
                version -= random.randint(1, min(3, version - 1))
            if event_type == "product.created":
                product.deleted = False
                product.categories = [random.choice(CATEGORIES)]
            elif event_type == "product.deleted":
                product.deleted = True
            elif event_type == "category.moved":
                old_category = product.categories[0]
                choices = [category for category in CATEGORIES if category != old_category]
                product.categories = [random.choice(choices)]

            data: dict = {"id": product.id, "version": version, "updated_at": self.timestamp(), "source_timestamp": self.timestamp()}
            if event_type == "product.created":
                data.update({
                    "name": self.fake.catch_phrase(), "sku": self.fake.ean13(),
                    "price": float(self.fake.pydecimal(left_digits=3, right_digits=2, positive=True, min_value=1, max_value=999)),
                    "inventory": self.fake.random_int(0, 500), "categories": product.categories,
                    "barcode": self.fake.ean13(), "brand": self.fake.company(),
                })
            elif event_type == "price.changed":
                data["price"] = float(self.fake.pydecimal(left_digits=3, right_digits=2, positive=True, min_value=1, max_value=999))
            elif event_type == "inventory.changed":
                data["inventory"] = self.fake.random_int(0, 1000)
            elif event_type == "metadata.changed":
                data["fields"] = {
                    "name": self.fake.catch_phrase(), "description": self.fake.text(max_nb_chars=140),
                    "tags": [self.fake.word() for _ in range(4)],
                    "attributes": {"material": self.fake.word(), "origin": self.fake.country_code(), "season": self.fake.random_element(("spring", "summer", "autumn", "winter"))},
                }
            elif event_type == "category.moved":
                data.update({"from": old_category, "to": product.categories[0]})
            elif event_type == "product.deleted":
                data["categories"] = product.categories
        return {"event_type": event_type, "data": data}

    def send(self) -> None:
        payload = self.make_payload()
        body = json.dumps(payload, separators=(",", ":")).encode()
        signature = hmac.new(self.args.secret.encode(), body, hashlib.sha256).hexdigest()
        try:
            response = requests.post(self.args.url, data=body, headers={"Content-Type": "application/json", "X-Supplier-Signature": signature}, timeout=self.args.timeout)
            with self.lock:
                self.sent += 1
                self.failed += response.status_code >= 400
        except requests.RequestException:
            with self.lock:
                self.sent += 1
                self.failed += 1

    def run(self) -> None:
        print(f"Simulating {self.args.rate} webhooks/sec across {self.args.pool_size} IDs; Ctrl+C to stop.")
        started = last_report = time.monotonic()
        try:
            with ThreadPoolExecutor(max_workers=self.args.workers) as executor:
                next_event = time.monotonic()
                while self.args.duration <= 0 or time.monotonic() - started < self.args.duration:
                    executor.submit(self.send)
                    next_event += 1 / self.args.rate
                    delay = next_event - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                    if time.monotonic() - last_report >= 5:
                        with self.lock:
                            print(f"queued={self.sent} http_failures={self.failed}")
                        last_report = time.monotonic()
        except KeyboardInterrupt:
            print("\nSimulator stopped.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Faker-powered supplier webhook stress simulator")
    parser.add_argument("--url", default=os.getenv("SIMULATOR_URL", "http://127.0.0.1:5001/api/v1/webhooks/supplier"))
    parser.add_argument("--secret", default=os.getenv("SUPPLIER_SECRET_WEBHOOK_KEY", "mock-supplier-webhook-secret"))
    parser.add_argument("--rate", type=float, default=100, help="webhooks per second")
    parser.add_argument("--workers", type=int, default=16, help="concurrent HTTP clients")
    parser.add_argument("--pool-size", type=int, default=20, help="small ID pool used to force contention")
    parser.add_argument("--stale-ratio", type=float, default=.20, help="fraction of deliberately older versions")
    parser.add_argument("--timeout", type=float, default=5)
    parser.add_argument("--duration", type=float, default=0, help="seconds; 0 runs until Ctrl+C")
    args = parser.parse_args()
    if args.rate <= 0 or args.workers <= 0 or args.pool_size <= 0 or not 0 <= args.stale_ratio <= 1:
        parser.error("rate, workers, and pool-size must be positive; stale-ratio must be 0..1")
    return args


if __name__ == "__main__":
    SupplierSimulator(parse_args()).run()
