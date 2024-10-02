from decouple import config
from socketio import AsyncRedisManager, AsyncServer

from lib.core.constants import EmitMessageKey
from lib.schemas.chat_message import ChatMessageCreate
from lib.services.chat_service import ChatService
from lib.utils.jwt import decode_jwt_token, verify_jwt_token

# Read redis host from env
REDIS_HOST = config("REDIS_HOST", default="127.0.0.1:6379")
REDIS_PASSWORD = config("REDIS_PASSWORD", default=None)
REDIS_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}/0"

chat_service = ChatService()

sio = AsyncServer(
    async_mode="asgi",
    client_manager=AsyncRedisManager(REDIS_URL),
    cors_allowed_origins=["http://127.0.0.1:5500"],
    logger=True,
)


@sio.event
async def connect(sid, environ):
    # Extract the query string
    query = environ.get("QUERY_STRING", "")

    # Extract the auth token from the query string
    token = None
    for param in query.split("&"):
        if param.startswith("authToken="):
            token = param.split("=")[1]
            break

    # Validate the token
    if not token or not verify_jwt_token(token):
        print(f"Client {sid} connection rejected: Invalid token")
        raise ConnectionRefusedError(
            "Invalid token"
        )  # Reject connection with an exception

    # Extract user_id from token
    payload = decode_jwt_token(token)
    if not payload:
        print(f"Client {sid} connection rejected: Invalid user ID")
        raise ConnectionRefusedError(
            "Invalid user ID"
        )  # Reject connection with an exception

    room_id = payload.get("sub")  # user_id
    await sio.enter_room(sid, room_id)
    print(f"Client {sid} connected to chat {room_id}")


@sio.event
async def disconnect(sid):
    print(f"Client {sid} disconnected")
    rooms = sio.rooms(sid)
    for room in rooms:
        await sio.leave_room(sid, room)


@sio.event
async def sendMessage(sid, data):
    chat_id = data.get("chat_id")
    sender_id = data.get("sender_id")
    content = data.get("content")
    media = data.get("media")
    reply_to = data.get("reply_to")
    timestamp = data.get("timestamp")
    metadata = data.get("metadata", {})

    # Ensure that required fields are present
    if not all([chat_id, sender_id, content]):
        return {"status": "error", "message": "Missing required fields"}

    # Create a message object
    message_data = ChatMessageCreate(
        chat_id=chat_id,
        sender_id=sender_id,
        content=content,
        media=media,
        reply_to=reply_to,
        timestamp=timestamp,
        metadata=metadata,
        severity="low",
        is_flagged=False,
    )

    try:
        # Save message and update unread counts
        await chat_service.add_message(message_data)

    except Exception as e:
        await sio.emit(
            "error", {"status": "error", "message": str(e)}, room=sid
        )


@sio.event
async def markAsRead(sid, data):
    chat_id = data.get("chat_id")
    user_id = data.get("user_id")
    message_id = data.get(
        "message_id", None
    )  # Optional: Mark a specific message or all

    # Ensure required fields are present
    if not all([chat_id, user_id]):
        return {"status": "error", "message": "Missing required fields"}

    try:
        # Fetch all messages in the chat if no message_id is provided (mark all as read)
        if not message_id:
            # Mark all messages as read for this user
            await chat_service.mark_all_messages_as_read(chat_id, user_id)
        else:
            # Mark specific message as read
            await chat_service.mark_message_as_read(
                chat_id, user_id, message_id
            )

        return {"status": "success", "message": "Messages marked as read"}

    except Exception as e:
        print(f"Error marking message as read: {str(e)}")
        return {"status": "error", "message": str(e)}


@sio.event
async def toggleReaction(sid, data):
    chat_id = data.get("chat_id")
    message_id = data.get("message_id")
    user_id = data.get("user_id")
    reaction = data.get("reaction")

    # Ensure required fields are present
    if not all([chat_id, message_id, user_id, reaction]):
        return {"status": "error", "message": "Missing required fields"}

    try:
        # Call toggle reaction in ChatService
        await chat_service.toggle_reaction(
            chat_id, message_id, user_id, reaction
        )

        # Fetch the updated message with the latest reactions
        updated_message = await chat_service.get_message_by_id(message_id)

        # Emit the updated reaction event to all participants in the chat
        await chat_service.emit_to_associated_participants(
            message_key=EmitMessageKey.MESSAGE_UPDATED.value,
            data={
                "chat_id": chat_id,
                "message": updated_message,
            },
            chat_id=chat_id,
        )

        return {
            "status": "success",
            "message": "Reaction toggled successfully",
        }

    except Exception as e:
        print(f"Error toggling reaction: {str(e)}")
        return {"status": "error", "message": str(e)}


@sio.event
async def list_rooms(sid):
    rooms = sio.rooms(sid)
    print(f"Listing rooms for {sid}: {rooms}")
    await sio.emit("rooms_list", rooms, room=sid)
