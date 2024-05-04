import json


def parse_json_garbage(s):
    s = s[next(idx for idx, c in enumerate(s) if c in "{["):]
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        return json.loads(s[:e.pos])
    
# def parse_json_garbage(s):
#     # Regular expression to match the JSON between ```json and ```
#     pattern = re.compile(r'```json\s*(\{.*\}|\[.*\])\s*```', re.DOTALL)
#     match = pattern.search(s)

#     def try_partial_json(json_str):
#         try:
#             return json.loads(json_str)
#         except json.JSONDecodeError as e:
#             return None

#     if not match:
#         # Attempt to match any JSON object or array
#         pattern = re.compile(r'(\{.*\}|\[.*\])', re.DOTALL)
#         match = pattern.search(s)

#     if match:
#         json_str = match.group(1)
#         result = try_partial_json(json_str)

#         if result is None:
#             # Attempt to find the longest valid JSON string
#             for i in range(len(json_str) - 1, 0, -1):
#                 partial_result = try_partial_json(json_str[:i])
#                 if partial_result is not None:
#                     return partial_result
#             return None
#         else:
#             return result
#     else:
#         print("==> No JSON object found")
#         return None