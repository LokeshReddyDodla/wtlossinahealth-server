import tiktoken

def count_tokens(message: str) -> int:
    print("==> Count tokens from message: %s" % message)
    encoding = tiktoken.encoding_for_model("gpt-4o")
    tokens = encoding.encode(message)
    return len(tokens)

def truncate_conversation_history(history: list, token_limit: int) -> list:
    print("Truncating conversation history : ", history)
    total_tokens = sum(count_tokens(m['content']) for m in history)
    while total_tokens > token_limit and history:
        removed_message = history.pop(0)
        total_tokens -= count_tokens(removed_message['content'])
    return history

def identify_context(document_type: str) -> str:
    # Simple mapping based on document type
    context_mapping = {
        "meal": "meal",
        "prescription": "prescription",
        "report": "report",
        "general": "general"
    }
    return context_mapping.get(document_type.lower(), "general")
