from datetime import datetime
from typing import Optional


def get_user_chat_pipeline(user_id: str):
    return [
        {"$match": {"participants.id": user_id}},
        {"$sort": {"updated_at": -1}},
        {
            "$lookup": {
                "from": "chat_messages",
                "localField": "last_message",
                "foreignField": "_id",
                "as": "last_message",
            }
        },
        {
            "$addFields": {
                "last_message": {
                    "$cond": {
                        "if": {"$gt": [{"$size": "$last_message"}, 0]},
                        "then": {"$arrayElemAt": ["$last_message", 0]},
                        "else": None,
                    }
                },
                "sender": {
                    "$arrayElemAt": [
                        {
                            "$filter": {
                                "input": "$participants",
                                "as": "participant",
                                "cond": {"$eq": ["$$participant.id", user_id]},
                            }
                        },
                        0,
                    ]
                },
                "receivers": {
                    "$filter": {
                        "input": "$participants",
                        "as": "participant",
                        "cond": {"$ne": ["$$participant.id", user_id]},
                    }
                },
            }
        },
        {
            "$project": {
                "_id": 1,
                "is_group": 1,
                "kind": 1,
                "participants": 1,
                "sender": 1,
                "receivers": 1,
                "unread_counts": 1,
                "last_message": 1,
                "updated_at": 1,
                "alias_name": 1,
                "alias_profile_picture": 1,
                "description": 1,
            }
        },
    ]


def get_single_chat_pipeline(chat_id: str, user_id: str):
    """Same shape as :func:`get_user_chat_pipeline`, restricted to a single
    chat. Conflates "chat doesn't exist" and "user isn't a participant"
    into one empty result so we don't leak existence."""
    pipeline = get_user_chat_pipeline(user_id)
    pipeline[0] = {
        "$match": {"_id": chat_id, "participants.id": user_id}
    }
    return pipeline


def get_user_messages_pipeline(
    user_id: str, last_sync_time: Optional[datetime] = None
):
    # Match against the chats collection by participant; it has no sender_id.
    match_condition = {"participants.id": user_id}

    pipeline = [
        {"$match": match_condition},  # Match the user in chats
        {
            "$lookup": {
                "from": "chat_messages",  # Join with chat_messages collection
                "localField": "_id",  # Matching chat _id with chat_id in messages
                "foreignField": "chat_id",
                "as": "messages",
            }
        },
        {
            "$unwind": "$messages"
        },  # Unwind the messages to filter them individually
    ]

    if last_sync_time:
        pipeline.append(
            {"$match": {"messages.updated_at": {"$gt": last_sync_time}}}
        )

    pipeline.append({"$sort": {"messages.updated_at": 1}})

    pipeline.append({"$replaceRoot": {"newRoot": "$messages"}})

    return pipeline


def get_chat_messages_pipeline(chat_id: str, before=None, limit: int = 50):
    # Page backwards from newest: match the chat (and messages older than the
    # `before` cursor when paging), take the newest `limit`. Callers reverse the
    # result to ascending for display.
    match_condition = {"chat_id": chat_id}
    if before is not None:
        match_condition["timestamp"] = {"$lt": before}

    return [
        {"$match": match_condition},
        {"$sort": {"timestamp": -1}},
        {"$limit": limit},
    ]
