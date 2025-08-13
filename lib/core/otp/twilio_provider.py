from twilio.rest import Client
from fastapi import HTTPException
from decouple import config
from .base import OTPProvider


class TwilioOTPProvider(OTPProvider):
    def __init__(self):
        self.account_sid = config("TWILIO_ACCOUNT_SID")
        self.auth_token = config("TWILIO_AUTH_TOKEN")
        self.from_whatsapp_number = config("TWILIO_WHATSAPP_FROM")
        self.from_number = config("TWILIO_SMS_FROM")
        self.client = Client(self.account_sid, self.auth_token)  # type: ignore
        self.content_sid = config("TWILIO_CONTENT_SID")

    async def send_otp(self, phone_number: str, otp: str) -> dict:
        try:
            message = self.client.messages.create(
                from_=self.from_whatsapp_number,
                content_sid=self.content_sid,
                content_variables=f'{{"1":"{otp}"}}',
                to=f"whatsapp:{phone_number}",
            )
            # message = self.client.messages.create(
            #     body="message_body", from_=self.from_number, to=phone_number
            # )
            return {"sid": message.sid, "status": message.status}
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Twilio send OTP failed: {str(e)}"
            )

    async def verify_otp(self, phone_number: str, otp: str) -> bool:
        # Twilio doesn’t provide OTP verification API for WhatsApp,
        # so you must verify OTP yourself (e.g. via cache)
        raise RuntimeError(
            "Twilio verification unavailable. Use cache_only=True "
            "and verify via cache store instead."
        )

    async def retry_otp(
        self, phone_number: str, retry_type: str = "text"
    ) -> dict:
        # Twilio doesn't have a retry API like MSG91,
        # You can implement resend logic if needed by calling send_otp again
        raise NotImplementedError(
            "Twilio OTP retry not supported via API, resend manually."
        )
