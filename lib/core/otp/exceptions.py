class OTPError(Exception):
    """Base exception for OTP-related errors."""

    pass


class OTPProviderError(OTPError):
    """Exception raised when OTP provider operations fail."""

    def __init__(self, message: str, provider: str = "unknown"):
        self.provider = provider
        super().__init__(f"[{provider}] {message}")


class OTPVerificationError(OTPError):
    """Exception raised when OTP verification fails."""

    pass


class OTPExpiredError(OTPError):
    """Exception raised when OTP has expired."""

    pass


class OTPNotFoundError(OTPError):
    """Exception raised when OTP is not found in cache."""

    pass
