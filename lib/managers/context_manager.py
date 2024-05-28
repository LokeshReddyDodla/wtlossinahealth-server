from datetime import datetime
import json
import logging
import os
from lib.utils.context_utils import identify_context, truncate_conversation_history


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ContextManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(ContextManager, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self, token_limit=3000, context_dir="contexts"):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self.token_limit = token_limit
            self.contexts = {}
            self.context_dir = context_dir
            if not os.path.exists(context_dir):
                os.makedirs(context_dir)
            
            logger.info("ContextManager initialized with token limit %d and context directory %s", token_limit, context_dir)
            
    def add_message(self, context_id: str, message: str, role: str, context_type = "unknown", media_url = None):
        if context_id not in self.contexts:
            self.contexts[context_id] = {
                "id": context_id,
                "type": context_type,
                "media_url": media_url,
                "created_at": datetime.now().isoformat(),
                "history": []
            }
        
        # Add message to in-memory context
        self.contexts[context_id]["history"].append({"role": role, "content": message})
        self.contexts[context_id]["history"] = truncate_conversation_history(self.contexts[context_id]["history"], self.token_limit)
        
        logger.info("Added message to context %s: %s", context_id, message)

    def get_context_window(self, context_id: str):
        if context_id in self.contexts:
            logger.info("Retrieved context window for %s: ", context_id)
            return self.contexts[context_id]
        
        logger.info("No context window found for %s: ", context_id)
        return {}

    def create_context(self, context_id: str, document_type: str):
        context = identify_context(document_type)
        if context_id not in self.contexts:
            self.contexts[context_id] = {
                "id": context_id,
                "type": context,
                "created_at": datetime.now().isoformat(),
                "history": []
            }
        
        logger.info("Created context %s with document type %s", context_id, document_type)
        
    def save_context_history_to_file(self, context_id: str, history: list):
        context_file = os.path.join(self.context_dir, f"{context_id}.json")
        with open(context_file, 'w') as f:
            json.dump(history, f, indent=4)

        logger.info("Saved context history for %s to file %s", context_id, context_file)

        
context_manager = ContextManager()
