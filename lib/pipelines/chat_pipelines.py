def get_individual_chat_pipeline(user_id: str):
    return [
        {"$match": {"participants.id": user_id}},
        {"$unwind": {"path": "$messages", "preserveNullAndEmptyArrays": True}},
        {"$sort": {"messages.timestamp": -1}},
        {
            "$group": {
                "_id": "$_id",
                "is_group": {"$first": "$is_group"},
                "participants": {"$first": "$participants"},
                "last_message": {"$first": "$messages"},
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
        },
        {
            "$addFields": {
                "chat_name": {
                    "$arrayElemAt": [
                        {
                            "$filter": {
                                "input": "$participants",
                                "as": "participant",
                                "cond": {"$ne": ["$$participant.id", user_id]},
                            }
                        },
                        0,
                    ]
                }
            }
        },
        # Only consider groups where last_message is not null to prevent incorrect unread counts
        {"$sort": {"last_message.timestamp": -1}},
    ]


def get_group_chat_pipeline(user_id: str):
    return [
        {"$match": {"participants.id": user_id}},
        {"$unwind": {"path": "$messages", "preserveNullAndEmptyArrays": True}},
        {"$sort": {"messages.timestamp": -1}},
        {
            "$group": {
                "_id": "$_id",
                "is_group": {"$first": "$is_group"},
                "participants": {"$first": "$participants"},
                "last_message": {"$first": "$messages"},
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
        },
        {"$sort": {"last_message.timestamp": -1}},
    ]
