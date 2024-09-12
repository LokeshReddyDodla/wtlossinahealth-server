from functools import partial, wraps
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.auth.care_provider_auth import (
    get_current_care_provider,
)
from lib.dependencies.care_provider.care_provider_permissions import (
    check_permissions,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from fastapi import HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from sqlalchemy.exc import SQLAlchemyError

from typing import Callable, List, Optional, Union
from sqlalchemy.future import select
from lib.schemas.care_provider import (
    CareProvider as CareProviderSchema,
    CareProviderCreate,
)
from sqlalchemy.exc import IntegrityError
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderRole,
    get_care_provider_permissions,
)
from rest_server.care_provider.api_schema import CareProviderResponse
from rest_server.response_models import SuccessResponse, ErrorResponse
from .router import router

from functools import wraps
from fastapi import HTTPException, Request, Depends
from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.utils.care_provider_permissions import (
    get_care_provider_permissions,
    CareProviderRole,
)


@router.post("", response_model=CareProviderResponse)
async def create_care_provider(
    request: Request,
    care_provider: CareProviderCreate,
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider("create", CareProviderFeature.CARE_PROVIDER)
    ),
) -> Union[CareProviderResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            role_enum = CareProviderRole(care_provider.role.lower())
            permissions = get_care_provider_permissions(role_enum)

            care_provider.permissions = permissions
            new_care_provider = CareProviderModel(**care_provider.dict())
            session.add(new_care_provider)
            await session.commit()
            await session.refresh(new_care_provider)

            return CareProviderResponse(
                message="Care Provider created successfully",
                data=CareProviderSchema.from_orm(new_care_provider),
            )
        except IntegrityError:
            raise HTTPException(
                status_code=400, detail="Care provider already exists."
            )
        except SQLAlchemyError as e:
            response = ErrorResponse(message="Database Error", detail=str(e))
            raise HTTPException(status_code=500, detail=response.dict())
