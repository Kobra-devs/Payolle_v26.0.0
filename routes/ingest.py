
import json
import hashlib
import hmac
import uuid

from flask import Blueprint, current_app, jsonify, request
from redis.exceptions import RedisError

from extensions import redis_client
from transformers import transform_event

ingest_bp = Blueprint("ingest", __name__)
SUPPORTED_FORMATS = {"jsonld", "csv", "xml"}
def verify_supplier_signature(payload: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    expected = hmac.new(
        current_app.config["SUPPLIER_SECRET_WEBHOOK_KEY"].encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    provided = signature.removeprefix("sha256=").strip()
    return hmac.compare_digest(provided, expected)


def _format_from_request() -> str | None:
    return (request.args.get("format") or request.headers.get("X-Catalog-Format") or "").lower().strip()


@ingest_bp.post("/webhooks/supplier")
def supplier_webhook():
    if not verify_supplier_signature(request.get_data(), request.headers.get("X-Supplier-Signature")):
        return jsonify(error="Invalid supplier webhook signature"), 401

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Webhook payload must be a JSON object"), 400

    try:
        update = transform_event(payload)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    try:
        redis_client.client.rpush(current_app.config["REDIS_PRIORITY_QUEUE"], json.dumps(update))
    except RedisError:
        current_app.logger.exception("Redis unavailable while queueing supplier webhook")
        return jsonify(error="Redis is unavailable; start Redis and retry"), 503
    return jsonify(status="queued"), 202


@ingest_bp.post("/ingest")
def ingest():
    file = request.files.get("file")
    file_format = _format_from_request()
    if file is None or not file.filename:
        return jsonify(error="A catalog file is required in the 'file' field"), 400
    if file_format not in SUPPORTED_FORMATS:
        return jsonify(error="format must be one of: jsonld, csv, xml"), 415
    content = file.read()
    if not content:
        return jsonify(error="The catalog file is empty"), 400
    if len(content) > current_app.config["MAX_CONTENT_LENGTH"]:
        return jsonify(error="The catalog file is too large"), 413

    try:
        document = content.decode("utf-8")
    except UnicodeDecodeError:
        return jsonify(error="The catalog file must be UTF-8 encoded"), 400

    task_id = str(uuid.uuid4())
    task_key = f"ingest_task:{task_id}"
    task = {"task_id": task_id, "format": file_format, "content": document}
    try:
        redis_client.client.hset(task_key, mapping={"status": "queued", "format": file_format})
        redis_client.client.expire(task_key, current_app.config["TASK_PAYLOAD_TTL_SECONDS"])
        redis_client.client.rpush(current_app.config["REDIS_TASK_QUEUE"], json.dumps(task))
    except RedisError:
        current_app.logger.exception("Redis unavailable while queueing task")
        return jsonify(error="Redis is unavailable; start Redis and retry"), 503
    return jsonify(task_id=task_id, status="queued"), 202


@ingest_bp.get("/tasks/<task_id>")
def task_status(task_id: str):
    try:
        task = redis_client.client.hgetall(f"ingest_task:{task_id}")
    except RedisError:
        return jsonify(error="Redis is unavailable; start Redis and retry"), 503
    if not task:
        return jsonify(error="Task not found"), 404
    return jsonify(task)
