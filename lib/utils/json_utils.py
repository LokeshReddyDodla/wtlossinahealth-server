def ensure_string_values(data):
    if isinstance(data, dict):
        return {
            key: ensure_string_values(value) for key, value in data.items()
        }
    elif isinstance(data, list):
        return [ensure_string_values(element) for element in data]
    elif isinstance(data, bool):
        return str(data).lower()  # JSON expects lowercase true/false
    elif data is None:
        return ""
    else:
        return str(data)
