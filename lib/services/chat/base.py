from lib.core.mongo_store import get_mongo_store


class BaseChatService:
    def __init__(self):
        self.mongo_store = get_mongo_store()
