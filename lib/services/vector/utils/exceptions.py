"""Custom exceptions for vector services."""


class VectorServiceError(Exception):
    """Base exception for vector service errors."""

    def __init__(self, message: str, service_name: str = "", **kwargs):
        super().__init__(message)
        self.service_name = service_name
        self.context = kwargs

    def __str__(self) -> str:
        base_msg = super().__str__()
        if self.service_name:
            return f"[{self.service_name}] {base_msg}"
        return base_msg


class EmbeddingError(VectorServiceError):
    """Exception raised when embedding generation fails."""

    pass


class PayloadValidationError(VectorServiceError):
    """Exception raised when payload validation fails."""

    def __init__(self, message: str, field: str = "", **kwargs):
        super().__init__(message, **kwargs)
        self.field = field


class PointIdGenerationError(VectorServiceError):
    """Exception raised when point ID generation fails."""

    pass
