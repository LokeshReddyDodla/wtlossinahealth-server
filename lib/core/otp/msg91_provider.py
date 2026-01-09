from typing import Any, Dict, Optional
import httpx
from decouple import config
from loguru import logger

from .base import OTPProvider
from .exceptions import OTPProviderError, OTPVerificationError

MSG91_BASE_URL: str = "https://control.msg91.com/api/v5/otp"
MSG91_AUTH_KEY: str = config("MSG91_AUTH_KEY", default="")
MSG91_TEMPLATE_ID: str = config("MSG91_TEMPLATE_ID", default="688b21dcd6fc05294a54e8e2")
MSG91_OTP_LENGTH: str = "4"
HTTP_TIMEOUT: int = 10


class Msg91OTPProvider(OTPProvider):
    def __init__(self, timeout: int = HTTP_TIMEOUT):
        if not MSG91_AUTH_KEY:
            raise ValueError("MSG91_AUTH_KEY is required")
        
        self.auth_key = MSG91_AUTH_KEY
        self.template_id = MSG91_TEMPLATE_ID
        self.base_url = MSG91_BASE_URL
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client instance."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def _close_client(self) -> None:
        """Close HTTP client if it exists."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def send_otp(
        self, phone_number: str, otp: Optional[str] = None
    ) -> Dict[str, Any]:
    
        payload = {
            "mobile": phone_number,
            "template_id": self.template_id,
            "otp_length": MSG91_OTP_LENGTH,
        }
        headers = {"Authkey": self.auth_key}

        try:
            client = await self._get_client()
            response = await client.post(
                self.base_url, json=payload, headers=headers
            )
            response.raise_for_status()
            
            result = response.json()
            logger.info(
                f"MSG91 OTP sent successfully to {phone_number}",
                extra={"phone_number": phone_number, "response": result}
            )
            return result
            
        except httpx.HTTPStatusError as e:
            logger.error(
                f"MSG91 send OTP failed with status {e.response.status_code}",
                extra={"phone_number": phone_number, "error": str(e)}
            )
            raise OTPProviderError(
                f"Failed to send OTP: HTTP {e.response.status_code}",
                provider="MSG91"
            ) from e
        except httpx.RequestError as e:
            logger.error(
                f"MSG91 send OTP request failed: {str(e)}",
                extra={"phone_number": phone_number}
            )
            raise OTPProviderError(
                f"Failed to send OTP: {str(e)}",
                provider="MSG91"
            ) from e

    async def verify_otp(self, phone_number: str, otp: str) -> bool:
        params = {"mobile": phone_number, "otp": otp}
        headers = {"Authkey": self.auth_key}

        try:
            client = await self._get_client()
            response = await client.get(
                f"{self.base_url}/verify", params=params, headers=headers
            )
            response.raise_for_status()
            
            data = response.json()
            if data.get("type") != "success":
                logger.warning(
                    f"MSG91 OTP verification failed for {phone_number}",
                    extra={"phone_number": phone_number, "response": data}
                )
                raise OTPVerificationError("Invalid OTP")
            
            logger.info(
                f"MSG91 OTP verified successfully for {phone_number}",
                extra={"phone_number": phone_number}
            )
            return True
            
        except OTPVerificationError:
            raise
        except httpx.HTTPStatusError as e:
            logger.error(
                f"MSG91 verify OTP failed with status {e.response.status_code}",
                extra={"phone_number": phone_number, "error": str(e)}
            )
            raise OTPProviderError(
                f"Failed to verify OTP: HTTP {e.response.status_code}",
                provider="MSG91"
            ) from e
        except httpx.RequestError as e:
            logger.error(
                f"MSG91 verify OTP request failed: {str(e)}",
                extra={"phone_number": phone_number}
            )
            raise OTPProviderError(
                f"Failed to verify OTP: {str(e)}",
                provider="MSG91"
            ) from e

    async def retry_otp(
        self, phone_number: str, retry_type: str = "text"
    ) -> Dict[str, Any]:
        params = {"mobile": phone_number, "retrytype": retry_type}
        headers = {"Authkey": self.auth_key}

        try:
            client = await self._get_client()
            response = await client.get(
                f"{self.base_url}/retry", params=params, headers=headers
            )
            response.raise_for_status()
            
            result = response.json()
            logger.info(
                f"MSG91 OTP retry sent successfully to {phone_number}",
                extra={"phone_number": phone_number, "retry_type": retry_type}
            )
            return result
            
        except httpx.HTTPStatusError as e:
            logger.error(
                f"MSG91 retry OTP failed with status {e.response.status_code}",
                extra={"phone_number": phone_number, "error": str(e)}
            )
            raise OTPProviderError(
                f"Failed to retry OTP: HTTP {e.response.status_code}",
                provider="MSG91"
            ) from e
        except httpx.RequestError as e:
            logger.error(
                f"MSG91 retry OTP request failed: {str(e)}",
                extra={"phone_number": phone_number}
            )
            raise OTPProviderError(
                f"Failed to retry OTP: {str(e)}",
                provider="MSG91"
            ) from e

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._close_client()
