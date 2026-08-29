"""SocketIO room registration and event fan-out."""

from flask_socketio import emit, join_room


def register_socket_events(socketio):
    @socketio.on("join_product_room")
    def join_product_room(product_id):
        room = f"product_{product_id}"
        join_room(room)
        emit("room_joined", {"room": room})

    @socketio.on("join_category_room")
    def join_category_room(category):
        room = f"category_{category}"
        join_room(room)
        emit("room_joined", {"room": room})


def broadcast_update(socketio, update: dict) -> None:
    event_type = update.get("event_type")
    if not event_type and update.get("id"):
        socketio.emit("product_changed", update, room=f"product_{update['id']}")
        return
    if event_type in {"price.changed", "inventory.changed", "metadata.changed"}:
        socketio.emit("product_changed", update, room=f"product_{update['id']}")
    elif event_type in {"product.created", "product.deleted", "category.moved"}:
        categories = update.get("categories", [])
        if update.get("new_category"):
            categories.append(update["new_category"])
        if update.get("old_category"):
            categories.append(update["old_category"])
        for category in set(categories):
            socketio.emit("category_changed", update, room=f"category_{category}")
