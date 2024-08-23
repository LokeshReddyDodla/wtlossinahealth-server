import re


def extract_json_from_response(response: str) -> str:
    # Regular expression to capture content between triple backticks
    match = re.search(r"```json\n(.*?)\n```", response, re.DOTALL)
    if match:
        return match.group(1).strip()
    return response.strip()
