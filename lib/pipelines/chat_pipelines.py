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


def get_chat_pipeline(
    user_id: str,
    fetch_last_message: bool = False,
    fetch_all_messages: bool = False,
    is_group: bool = False,
):
    pipeline = [
        {"$match": {"participants.id": user_id}},
        {"$unwind": {"path": "$messages", "preserveNullAndEmptyArrays": True}},
        {"$sort": {"messages.timestamp": -1}},
    ]

    group_stage = {
        "_id": "$_id",
        "is_group": {"$first": "$is_group"},
        "participants": {"$first": "$participants"},
        "updated_at": {"$first": "$updated_at"},
        "unread_count": {
            "$sum": {
                "$cond": {
                    "if": {
                        "$and": [
                            {
                                "$ne": ["$messages", []]
                            },  # Check if messages exist
                            {
                                "$ne": ["$messages.read_receipts", []]
                            },  # Check if read_receipts exist
                            {
                                "$not": {
                                    "$in": [
                                        user_id,
                                        {
                                            "$ifNull": [
                                                "$messages.read_receipts.reader_id",
                                                [],
                                            ]
                                        },
                                    ]
                                }
                            },
                        ]
                    },
                    "then": 0,
                    "else": 1,
                }
            }
        },
    }

    if fetch_last_message:
        group_stage["last_message"] = {"$first": "$messages"}

    if fetch_all_messages:
        group_stage["messages"] = {"$push": "$messages"}

    pipeline.append({"$group": group_stage})

    if not is_group:
        pipeline.append(
            {
                "$addFields": {
                    "chat_name": {
                        "$arrayElemAt": [
                            {
                                "$filter": {
                                    "input": "$participants",
                                    "as": "participant",
                                    "cond": {
                                        "$ne": ["$$participant.id", user_id]
                                    },
                                }
                            },
                            0,
                        ]
                    }
                }
            }
        )

    # Final sort by updated_at to get most recent chats first
    pipeline.append({"$sort": {"updated_at": -1}})

    return pipeline
