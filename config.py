import os


class Config:
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    REDIS_TASK_QUEUE = os.getenv("REDIS_TASK_QUEUE", "product_ingest_tasks")
    REDIS_PRIORITY_QUEUE = os.getenv("REDIS_PRIORITY_QUEUE", "priority_updates")
    REDIS_UPDATES_CHANNEL = os.getenv("REDIS_UPDATES_CHANNEL", "product_updates")
    SOCKETIO_CHANNEL = os.getenv("SOCKETIO_CHANNEL", "chatpay_socketio")
    SOCKETIO_CORS_ALLOWED_ORIGINS = os.getenv("SOCKETIO_CORS_ALLOWED_ORIGINS", "*")
    SUPPLIER_SECRET_WEBHOOK_KEY = os.getenv("SUPPLIER_SECRET_WEBHOOK_KEY", "mock-supplier-webhook-secret")
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(10 * 1024 * 1024)))
    TASK_PAYLOAD_TTL_SECONDS = int(os.getenv("TASK_PAYLOAD_TTL_SECONDS", "3600"))
    ENABLE_PUBSUB_BRIDGE = os.getenv("ENABLE_PUBSUB_BRIDGE", "true").lower() == "true"
    PORT = int(os.getenv("PORT", "5001"))
