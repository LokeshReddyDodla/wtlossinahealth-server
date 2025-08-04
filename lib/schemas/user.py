from typing import Optional

from pydantic import BaseModel, Field


class UserPhoneNumber(BaseModel):
    phone_number: str


class OtpVerificationData(BaseModel):
    phone_number: str
    otp: str
    fcm_token: Optional[str] = Field(
        None, description="FCM token of the user's device"
    )
    device_type: Optional[str] = Field(
        None, description="Type of the user's device (e.g., iOS, Android)"
    )
    platform_version: Optional[str] = Field(
        None,
        description="Version of the platform (e.g., iOS 14.5, Android 11)",
    )
    device_model: Optional[str] = Field(
        None, description="Model name of the device"
    )
    manufacturer: Optional[str] = Field(
        None, description="Device manufacturer (e.g., Apple, Samsung)"
    )
    device_name: Optional[str] = Field(
        None, description="User-friendly device name"
    )
    is_physical_device: Optional[bool] = Field(
        None, description="True if this is a real device"
    )
    app_name: Optional[str] = Field(None, description="App name")
    app_version: Optional[str] = Field(
        None, description="App version and build"
    )
    latitude: Optional[float] = Field(
        None, description="Latitude of the user's location"
    )
    longitude: Optional[float] = Field(
        None, description="Longitude of the user's location"
    )
    location_name: Optional[str] = Field(
        None, description="Human-readable location name"
    )
