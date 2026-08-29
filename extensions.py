import json
import threading

import redis

from sockets import broadcast_update

REDIS_SOCKET_TIMEOUT = 3


class RedisClient:
    def __init__(self):
        self.client = None

    def init_app(self, app):
        self.client = redis.Redis.from_url(
            app.config["REDIS_URL"],
            decode_responses=True,
            socket_connect_timeout=REDIS_SOCKET_TIMEOUT,
            socket_timeout=REDIS_SOCKET_TIMEOUT,
        )


redis_client = RedisClient()


def start_update_bridge(app, socketio):
    """Forward domain update events to SocketIO clients in the web process."""
    def listen():
        client = redis.Redis.from_url(
            app.config["REDIS_URL"],
            decode_responses=True,
            socket_connect_timeout=REDIS_SOCKET_TIMEOUT,
            socket_timeout=REDIS_SOCKET_TIMEOUT,
        )
        try:
            subscriber = client.pubsub()
            subscriber.subscribe(app.config["REDIS_UPDATES_CHANNEL"])
            for message in subscriber.listen():
                if message.get("type") != "message":
                    continue
                try:
                    payload = json.loads(message["data"])
                except (TypeError, json.JSONDecodeError):
                    app.logger.warning("Ignoring malformed product update")
                    continue
                broadcast_update(socketio, payload)
        except redis.RedisError:
            app.logger.warning("Redis unavailable; live updates are disabled")

    thread = threading.Thread(target=listen, name="product-update-bridge", daemon=True)
    thread.start()
