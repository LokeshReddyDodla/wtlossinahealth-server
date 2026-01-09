from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class OTPProvider(ABC):
    @abstractmethod
    async def send_otp(
        self, phone_number: str, otp: Optional[str] = None
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def verify_otp(self, phone_number: str, otp: str) -> bool:
        pass

    @abstractmethod
    async def retry_otp(
        self, phone_number: str, retry_type: str = "text"
    ) -> Dict[str, Any]:
        pass
