
from typing import Optional
from loguru import logger

from lib.core.cache_store import CacheStore
from .base import OTPProvider
from .exceptions import (
    OTPError,
    OTPExpiredError,
    OTPNotFoundError,
    OTPVerificationError,
    OTPProviderError,
)
from .utils import generate_otp, DEFAULT_OTP_LENGTH

OTP_EXPIRY_TIME: int = 300
OTP_LENGTH: int = 4
MASTER_OTP: Optional[str] = None


class OTPService:
    def __init__(
        self,
        provider: OTPProvider,
        cache_store: CacheStore,
        otp_length: int = OTP_LENGTH,
        otp_expiry: int = OTP_EXPIRY_TIME,
        master_otp: Optional[str] = None,
    ):
        self.provider = provider
        self.cache_store = cache_store
        self.otp_length = otp_length
        self.otp_expiry = otp_expiry
        self.master_otp = master_otp or MASTER_OTP

    async def generate_and_send_otp(
        self, phone_number: str, send_via_provider: bool = False
    ) -> str:
        otp = generate_otp(length=self.otp_length)
        self.cache_store.set_key(phone_number, otp, self.otp_expiry)
        
        if send_via_provider:
            try:
                await self.provider.send_otp(phone_number, otp)
                logger.info(
                    f"OTP sent via provider to {phone_number}",
                    extra={"phone_number": phone_number}
                )
            except OTPProviderError as e:
                logger.error(
                    f"Failed to send OTP via provider: {str(e)}",
                    extra={"phone_number": phone_number}
                )
        
        logger.info(
            f"OTP generated and stored for {phone_number}",
            extra={"phone_number": phone_number, "otp_length": self.otp_length}
        )
        return otp

    async def verify_otp(
        self, phone_number: str, otp: str, cache_only: bool = False
    ) -> bool:
        if self.master_otp and otp == self.master_otp:
            logger.warning(
                f"Master OTP used for verification: {phone_number}",
                extra={"phone_number": phone_number}
            )
            return True

        stored_otp_bytes = self.cache_store.get_key(phone_number)
        
        if stored_otp_bytes is None:
            logger.warning(
                f"OTP not found in cache for {phone_number}",
                extra={"phone_number": phone_number}
            )
            if cache_only:
                return False
            raise OTPNotFoundError("OTP not found or has expired")

        stored_otp = stored_otp_bytes.decode("utf-8")

        if stored_otp == otp:
            self.cache_store.delete_key(phone_number)
            logger.info(
                f"OTP verified successfully for {phone_number}",
                extra={"phone_number": phone_number}
            )
            return True

        logger.warning(
            f"Invalid OTP provided for {phone_number}",
            extra={"phone_number": phone_number}
        )

        if cache_only:
            return False

        try:
            return await self.provider.verify_otp(phone_number, otp)
        except OTPProviderError as e:
            logger.error(
                f"Provider verification failed: {str(e)}",
                extra={"phone_number": phone_number}
            )
            raise OTPVerificationError("OTP verification failed") from e

    async def retry_otp(
        self, phone_number: str, retry_type: str = "text"
    ) -> dict:
        try:
            result = await self.provider.retry_otp(phone_number, retry_type)
            logger.info(
                f"OTP retry sent successfully to {phone_number}",
                extra={"phone_number": phone_number, "retry_type": retry_type}
            )
            return result
        except NotImplementedError:
            logger.warning(
                f"OTP retry not supported by provider for {phone_number}",
                extra={"phone_number": phone_number}
            )
            raise
        except OTPProviderError as e:
            logger.error(
                f"OTP retry failed: {str(e)}",
                extra={"phone_number": phone_number}
            )
            raise
