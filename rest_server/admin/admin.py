from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.core.constants import ProfileType
from lib.dependencies.database import get_postgres_session
from lib.models.admin import Admin
from lib.utils.jwt import create_jwt_token
from lib.utils.security import hash_password, verify_password
from lib.utils.validators import validate_email
from rest_server.response_models import ErrorResponse, SuccessResponse

router = APIRouter(prefix="/admin")


class AdminCreate(BaseModel):
    email: str
    password: str

    @validator("email")
    def validate_email_format(cls, value):
        return validate_email(value)


@router.post("/register", tags=["Admin"], response_model=SuccessResponse)
async def register_admin(
    request: Request,
    admin_data: AdminCreate,
    session: AsyncSession = Depends(get_postgres_session),
):
    try:
        # Check if the admin already exists
        existing_admin = await session.execute(
            select(Admin).filter(Admin.email == admin_data.email)
        )
        existing_admin = existing_admin.scalars().first()

        if existing_admin:
            raise HTTPException(
                status_code=400,
                detail="Admin with this email already exists",
            )

        # Create a new admin
        hashed_password = hash_password(admin_data.password)
        new_admin = Admin(
            email=admin_data.email, hashed_password=hashed_password
        )
        session.add(new_admin)
        await session.commit()
        await session.refresh(new_admin)

        return SuccessResponse(
            message="Admin registered successfully",
            data={"email": new_admin.email},
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())


@router.post("/login", tags=["Admin"], response_model=SuccessResponse)
async def login_admin(
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
    form_data: OAuth2PasswordRequestForm = Depends(),
):

    try:
        result = await session.execute(
            select(Admin).filter(Admin.email == form_data.username)
        )
        admin = result.scalars().first()

        if not admin or not verify_password(
            form_data.password, admin.hashed_password # type: ignore
        ):
            raise HTTPException(
                status_code=400, detail="Invalid email or password"
            )

        token = create_jwt_token(
            user_id=str(admin.id), role=ProfileType.ADMIN.value
        )
        return SuccessResponse(message="User verified", data={"token": token})
    except HTTPException as e:
        raise e
    except Exception as e:
        return ErrorResponse(message="Failed to authenticate", detail=str(e))
