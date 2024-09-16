from datetime import datetime


def serialize_message(message):
    """Convert the message to a JSON-serializable format."""
    for key, value in message.items():
        if isinstance(value, datetime):
            # Convert datetime objects to ISO 8601 strings
            message[key] = value.isoformat()
        elif isinstance(value, dict):
            # Recursively serialize nested dictionaries
            message[key] = serialize_message(value)
    return message
