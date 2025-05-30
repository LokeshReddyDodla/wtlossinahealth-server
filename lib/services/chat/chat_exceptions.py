class ChatCreationError(Exception):
    """Raised when chat relationship creation fails"""

    def __init__(self, message="Failed to create chat relationships"):
        self.message = message
        super().__init__(self.message)
