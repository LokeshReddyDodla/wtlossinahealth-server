import re


def extract_uuid_from_string(input_string: str) -> str:
    match = re.search(r"[0-9a-fA-F-]{36}", input_string)
    return match.group(0) if match else ""


def extract_path_segment(input_string: str, position: int) -> str:
    segments = input_string.strip("/").split("/")
    return segments[position] if len(segments) > position else ""
