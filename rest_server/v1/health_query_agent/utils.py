def resolve_bot_conversation_id(actor_type, actor_id, subject_patient_id=None):
    if actor_type == "patient":
        return f"bot:patient:{actor_id}"

    if actor_type == "care_provider" and subject_patient_id:
        return f"bot:provider:{actor_id}:patient:{subject_patient_id}"

    if actor_type == "care_provider":
        return f"bot:provider:{actor_id}"

    # Fallback for other actor types (e.g., admin)
    return f"bot:{actor_type}:{actor_id}"
