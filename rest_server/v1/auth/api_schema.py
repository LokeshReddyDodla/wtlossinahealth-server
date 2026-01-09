from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from rest_server.response_models import SuccessResponse


# Request Models
class SendOtpRequest(BaseModel):
    phone_number: str = Field(..., description="Phone number to send OTP to")


class VerifyOtpRequest(BaseModel):
    phone_number: str = Field(..., description="Phone number to verify")
    otp: str = Field(..., description="OTP code to verify")
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


class CareProviderLoginRequest(BaseModel):
    email: str = Field(..., description="Care provider email address")
    password: str = Field(..., description="Care provider password")
    fcm_token: Optional[str] = Field(
        None, description="FCM token of the user's device"
    )
    device_type: Optional[str] = Field(
        None, description="Type of the user's device (e.g., iOS, Android)"
    )
    platform_version: Optional[str] = Field(
        None, description="Version of the platform"
    )


class LogoutRequest(BaseModel):
    device_id: Optional[str] = Field(
        None, description="Device ID to logout from"
    )


# Response Models
class AuthTokenResponse(BaseModel):
    token: str = Field(..., description="JWT authentication token")
    user_id: str = Field(..., description="User ID")
    device_id: Optional[str] = Field(None, description="Device ID")


class UserDeviceResponse(BaseModel):
    device_id: str = Field(..., description="Device ID")
    device_type: Optional[str] = Field(None, description="Device type (e.g., iOS, Android)")
    device_name: Optional[str] = Field(None, description="Device name")
    device_model: Optional[str] = Field(None, description="Device model")
    manufacturer: Optional[str] = Field(None, description="Device manufacturer")
    platform_version: Optional[str] = Field(None, description="Platform version")
    app_name: Optional[str] = Field(None, description="App name")
    app_version: Optional[str] = Field(None, description="App version")
    last_active_at: Optional[datetime] = Field(None, description="Last active timestamp")
    created_at: Optional[datetime] = Field(None, description="Device creation timestamp")


class UserDevicesListResponse(BaseModel):
    devices: List[UserDeviceResponse] = Field(..., description="List of user devices")
    total: int = Field(..., description="Total number of devices")


# Typed Success Responses
SendOtpResponse = SuccessResponse[None]  # Only message, no data
VerifyOtpResponse = SuccessResponse[AuthTokenResponse]
CareProviderLoginResponse = SuccessResponse[AuthTokenResponse]
LogoutResponse = SuccessResponse[None]  # Only message, no data
ListDevicesResponse = SuccessResponse[UserDevicesListResponse]
DeleteDeviceResponse = SuccessResponse[None]  # Only message, no data
DeleteAllDevicesResponse = SuccessResponse[None]  # Only message, no data