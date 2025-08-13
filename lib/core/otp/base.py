from abc import ABC, abstractmethod


class OTPProvider(ABC):
    @abstractmethod
    async def send_otp(self, phone_number: str, otp: str) -> dict:
        """Send OTP to the phone number."""
        pass

    @abstractmethod
    async def verify_otp(self, phone_number: str, otp: str) -> bool:
        """Verify the OTP for the phone number."""
        pass

    @abstractmethod
    async def retry_otp(
        self, phone_number: str, retry_type: str = "text"
    ) -> dict:
        """Retry sending the OTP (e.g., resend via SMS or voice)."""
        pass
