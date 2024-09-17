from decouple import config
from socketio import AsyncRedisManager, AsyncServer

from lib.utils.string_utils import extract_uuid_from_string

# Read redis host from env
REDIS_HOST = config("REDIS_HOST", default="127.0.0.1:6379")
REDIS_PASSWORD = config("REDIS_PASSWORD", default=None)
REDIS_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}/0"

sio = AsyncServer(
    async_mode="asgi",
    client_manager=AsyncRedisManager(REDIS_URL),
    cors_allowed_origins=["http://127.0.0.1:5500"],
    logger=True,
)


@sio.event
async def connect(sid, environ):
    path = environ["PATH_INFO"]
    room_id = extract_uuid_from_string(path)
    await sio.enter_room(sid, room_id)
    print(f"Client {sid} connected to chat {room_id}")


@sio.event
async def disconnect(sid):
    print(f"Client {sid} disconnected")
    rooms = sio.rooms(sid)
    for room in rooms:
        await sio.leave_room(sid, room)


@sio.event
async def message(sid, data):
    room = data.get("room")
    message = data.get("message")
    print(f"Message from {sid} in room {room}: {message}")
    await sio.emit("message", {"message": message}, room=room)


@sio.event
async def list_rooms(sid):
    rooms = sio.rooms(sid)
    print(f"Listing rooms for {sid}: {rooms}")
    await sio.emit("rooms_list", rooms, room=sid)
