from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.database import get_postgres_session
from lib.dependencies.device_access import (
    authorize_device_access,
    resolve_profile_type,
)
from lib.dependencies.service_dependencies import get_token_usage_service
from lib.services.token_usage_service import TokenUsageService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .api_schema import (
    ListTokenUsageResponse,
    TokenUsageDayResponse,
    TokenUsageListResponse,
)
from .router import router


@router.get(
    "",
    response_model=ListTokenUsageResponse,
    summary="List Token Usage",
    description=(
        "Get token usage for a user, grouped by date. "
        "If user_id is not provided, fetches token usage for the authenticated user. "
        "Patients can only fetch their own token usage. "
        "Care providers can fetch their own token usage or their patients' token usage. "
        "Admins can fetch any user's token usage."
    ),
)
async def list_token_usage(
    start_date: date = Query(
        ..., description="Start date for token usage query (YYYY-MM-DD)"
    ),
    end_date: date = Query(
        ..., description="End date for token usage query (YYYY-MM-DD)"
    ),
    user_id: Optional[str] = Query(
        None,
        description="User ID to fetch token usage for (optional, defaults to authenticated user)",
    ),
    token_data: tuple = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
    token_usage_service: TokenUsageService = Depends(get_token_usage_service),
) -> ListTokenUsageResponse:
    try:
        if end_date < start_date:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="End date must be greater than or equal to start date",
            )

        current_user_id, role_value = token_data
        current_role = ProfileTypeEnum(role_value)

        # Determine target user_id (default to authenticated user if not provided)
        target_user_id = UUID(user_id) if user_id else UUID(current_user_id)

        # Resolve the profile type of the target user
        target_role = await resolve_profile_type(session, target_user_id)

        # Authorize access based on roles (using same logic as device access)
        await authorize_device_access(
            session=session,
            current_user_id=UUID(current_user_id),
            current_role=current_role,
            target_user_id=target_user_id,
            target_role=target_role,
        )

        # Get token usage summary
        usage_summary = await token_usage_service.get_usage_summary(
            user_id=str(target_user_id),
            user_type=target_role,
            start_date=start_date,
            end_date=end_date,
        )

        usage_responses = [
            TokenUsageDayResponse(
                date=day_usage["date"],
                total_input_tokens=day_usage["total_input_tokens"] or 0,
                total_output_tokens=day_usage["total_output_tokens"] or 0,
                total_cached_input_tokens=day_usage.get("total_cached_input_tokens"),
                total_cost=day_usage["total_cost"] if day_usage["total_cost"] is not None else Decimal('0'),
            )
            for day_usage in usage_summary
        ]

        return SuccessResponse(
            message="Token usage retrieved successfully",
            data=TokenUsageListResponse(
                usage=usage_responses,
                total=len(usage_responses),
            ),
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Invalid user ID format or date range",
            detail=str(e),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to retrieve token usage",
            detail=str(e),
        )
