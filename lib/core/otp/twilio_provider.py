from typing import Any, Dict, Optional
from twilio.rest import Client
from twilio.base.exceptions import TwilioException
from decouple import config
from loguru import logger

from .base import OTPProvider
from .exceptions import OTPProviderError, OTPVerificationError


class TwilioOTPProvider(OTPProvider):
    def __init__(self):
        self.account_sid = config("TWILIO_ACCOUNT_SID", default="")
        self.auth_token = config("TWILIO_AUTH_TOKEN", default="")
        self.from_whatsapp_number = config("TWILIO_WHATSAPP_FROM", default="")
        self.from_number = config("TWILIO_SMS_FROM", default="")
        self.content_sid = config("TWILIO_CONTENT_SID", default="")

        if not all([self.account_sid, self.auth_token]):
            raise ValueError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are required")

        if not self.from_whatsapp_number and not self.from_number:
            raise ValueError("Either TWILIO_WHATSAPP_FROM or TWILIO_SMS_FROM is required")

        try:
            self.client = Client(self.account_sid, self.auth_token)
        except Exception as e:
            raise ValueError(f"Failed to initialize Twilio client: {str(e)}") from e

    async def send_otp(
        self, phone_number: str, otp: Optional[str] = None
    ) -> Dict[str, Any]:
        if not otp:
            raise ValueError("OTP is required for Twilio provider")

        try:
            message = self.client.messages.create(
                from_=self.from_whatsapp_number,
                content_sid=self.content_sid,
                content_variables=f'{{"1":"{otp}"}}',
                to=f"whatsapp:{phone_number}",
            )
            
            result = {"sid": message.sid, "status": message.status}
            logger.info(
                f"Twilio OTP sent successfully to {phone_number}",
                extra={
                    "phone_number": phone_number,
                    "message_sid": message.sid,
                    "status": message.status
                }
            )
            return result
            
        except TwilioException as e:
            logger.error(
                f"Twilio send OTP failed: {str(e)}",
                extra={"phone_number": phone_number, "error": str(e)}
            )
            raise OTPProviderError(
                f"Failed to send OTP: {str(e)}",
                provider="Twilio"
            ) from e
        except Exception as e:
            logger.error(
                f"Unexpected error sending Twilio OTP: {str(e)}",
                extra={"phone_number": phone_number}
            )
            raise OTPProviderError(
                f"Unexpected error sending OTP: {str(e)}",
                provider="Twilio"
            ) from e

    async def verify_otp(self, phone_number: str, otp: str) -> bool:
        logger.warning(
            f"Twilio verify_otp called for {phone_number} - "
            "Twilio doesn't support OTP verification API"
        )
        raise OTPProviderError(
            "Twilio verification unavailable. Use cache_only=True "
            "and verify via cache store instead.",
            provider="Twilio"
        )

    async def retry_otp(
        self, phone_number: str, retry_type: str = "text"
    ) -> Dict[str, Any]:
        logger.warning(
            f"Twilio retry_otp called for {phone_number} - "
            "Twilio doesn't support retry API"
        )
        raise NotImplementedError(
            "Twilio OTP retry not supported via API. "
            "Resend by calling send_otp again."
        )
