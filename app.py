# Eventlet must patch sockets before Flask-SocketIO, Redis, or threading are
# imported; Socket.IO's Redis manager otherwise cannot use its pub/sub socket.
import eventlet

eventlet.monkey_patch()

from flask import Flask, render_template
from flask_socketio import SocketIO
from redis.exceptions import RedisError

from config import Config
from extensions import redis_client, start_update_bridge
from routes.ingest import ingest_bp
from sockets import register_socket_events

socketio = SocketIO(async_mode="eventlet", cors_allowed_origins="*")


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    redis_client.init_app(app)
    socketio.init_app(
        app,
        message_queue=app.config["REDIS_URL"],
        channel=app.config["SOCKETIO_CHANNEL"],
        cors_allowed_origins=app.config["SOCKETIO_CORS_ALLOWED_ORIGINS"],
    )
    register_socket_events(socketio)
    app.register_blueprint(ingest_bp, url_prefix="/api/v1")

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/dashboard")
    def dashboard():
        return render_template("dashboard.html")

    @app.get("/health")
    def health():
        try:
            redis_client.client.ping()
        except RedisError:
            return {"status": "degraded", "redis": "unavailable"}, 503
        return {"status": "ok"}

    if app.config.get("ENABLE_PUBSUB_BRIDGE", True):
        start_update_bridge(app, socketio)

    return app


app = create_app()


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=app.config["PORT"])
