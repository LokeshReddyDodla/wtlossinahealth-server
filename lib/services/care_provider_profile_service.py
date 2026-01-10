from datetime import datetime
import random
import re
import string
from typing import Dict, List, Optional, Set

from fastapi import status
from sqlalchemy import and_, distinct, exists, func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from lib.core.constants import EmitMessageKeyEnum
from lib.core.postgres_store import PostgresStore
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.models.patient import Patient as PatientModel
from lib.models.patient_connected_app import PatientConnectedApp
from lib.models.patient_package_assignment import (
    PatientPackageAssignment as PatientPackageAssignmentModel,
)
from lib.models.patient_smbg import PatientSMBG
from lib.schemas.care_provider import (
    CareProviderCreate,
    CareProviderUpdate,
    PermissionActionSchema,
)
from lib.services.chat.chat_management_service import ChatManagementService
from lib.services.chat.chat_notification_service import ChatNotificationService
from lib.utils.care_provider_permissions import (
    CareProviderRole,
    get_care_provider_permissions,
)
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session
from lib.utils.security import hash_password, verify_password
from dateutil.relativedelta import relativedelta


class CareProviderProfileService:
    PROFILE_SECTION_REQUIREMENTS: Dict[str, Set[str]] = {
        "personal_info": {
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "role",
        },
        "medical_info": {"medical_council_number"},
    }

    def __init__(
        self,
        postgres_store: PostgresStore,
        chat_notification_service: ChatNotificationService,
        chat_management_service: ChatManagementService,
    ):
        self.postgres_store = postgres_store
        self.chat_management_service = chat_management_service
        self.chat_notification_service = chat_notification_service

    @with_postgres_session
    async def fetch_care_provider(
        self,
        care_provider_id: str,
        detailed: Optional[bool] = False,
        *,
        postgres_session: AsyncSession,
    ) -> CareProviderModel:
        try:
            stmt = select(CareProviderModel).where(
                CareProviderModel.care_provider_id == care_provider_id
            )

            if detailed:
                stmt = stmt.options(
                    selectinload(CareProviderModel.health_facility),
                    selectinload(CareProviderModel.patients),
                    selectinload(CareProviderModel.packages),
                    selectinload(CareProviderModel.created_packages),
                )

            result = await postgres_session.execute(stmt)
            care_provider = result.scalars().first()

            if not care_provider:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Care provider not found.",
                )

            return care_provider

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def fetch_care_provider_profiles(
        self, care_provider_ids: List[str], *, postgres_session: AsyncSession
    ) -> Dict[str, CareProviderModel]:
        try:
            stmt = select(CareProviderModel).where(
                CareProviderModel.care_provider_id.in_(care_provider_ids)
            )
            result = await postgres_session.execute(stmt)
            profiles = result.scalars().all()

            return {
                str(profile.care_provider_id): profile for profile in profiles
            }

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def fetch_care_provider_patients(
        self,
        care_provider_id: str,
        role: str,
        health_facility_id: str,
        search: Optional[str] = None,
        age: Optional[List[str]] = None,
        gender: Optional[List[str]] = None,
        monitoringMethod: Optional[List[str]] = None,
        package: Optional[List[str]] = None,
        connected_apps: Optional[List[str]] = None,
        *,
        postgres_session: AsyncSession,
    ) -> List[PatientModel]:
        try:
            stmt = select(PatientModel).options(
                selectinload(PatientModel.health_facility),
                selectinload(PatientModel.care_providers),
                selectinload(PatientModel.package_assignments).options(
                    selectinload(PatientPackageAssignmentModel.package)
                ),
            )

            # Facility scope (for admin role)
            if role == "admin" and health_facility_id:
                stmt = stmt.where(
                    PatientModel.health_facility_id == health_facility_id
                )
            else:
                stmt = stmt.join(PatientModel.care_providers).where(
                    CareProviderModel.care_provider_id == care_provider_id
                )

            # Search filter
            if search:
                search_pattern = f"%{search}%"
                stmt = stmt.where(
                    or_(
                        PatientModel.first_name.ilike(search_pattern),
                        PatientModel.last_name.ilike(search_pattern),
                        PatientModel.email.ilike(search_pattern),
                        PatientModel.phone_number.ilike(search_pattern),
                    )
                )

            # gender filter
            if gender:
                stmt = stmt.where(PatientModel.gender.in_(gender))

            # age filter (convert ranges → DOB)
            if age:
                age_group_conditions = []
                today = datetime.today().date()

                for group in age:
                    if group == "under18":
                        cutoff_18 = today - relativedelta(years=18)
                        age_group_conditions.append(
                            PatientModel.dob > cutoff_18
                        )

                    elif group == "18-25":
                        cutoff_25 = today - relativedelta(years=25)
                        cutoff_18 = today - relativedelta(years=18)
                        age_group_conditions.append(
                            PatientModel.dob.between(cutoff_25, cutoff_18)
                        )

                    elif group == "26-35":
                        cutoff_35 = today - relativedelta(years=35)
                        cutoff_26 = today - relativedelta(years=26)
                        age_group_conditions.append(
                            PatientModel.dob.between(cutoff_35, cutoff_26)
                        )

                    elif group == "36-45":
                        cutoff_45 = today - relativedelta(years=45)
                        cutoff_36 = today - relativedelta(years=36)
                        age_group_conditions.append(
                            PatientModel.dob.between(cutoff_45, cutoff_36)
                        )

                    elif group == "46-60":
                        cutoff_60 = today - relativedelta(years=60)
                        cutoff_46 = today - relativedelta(years=46)
                        age_group_conditions.append(
                            PatientModel.dob.between(cutoff_60, cutoff_46)
                        )

                    elif group == "60+":
                        cutoff_60 = today - relativedelta(years=60)
                        age_group_conditions.append(
                            PatientModel.dob <= cutoff_60
                        )

                if age_group_conditions:
                    stmt = stmt.where(or_(*age_group_conditions))

            # type filter (SMBG data check)
            if monitoringMethod:
                type_conditions = []

                for data_type in monitoringMethod:
                    if data_type == "smbg":
                        type_conditions.append(
                            exists().where(
                                PatientSMBG.patient_id
                                == PatientModel.patient_id
                            )
                        )
                    elif data_type == "cgm":
                        # Check if patient has any CGM data (if you have a CGM model)
                        # type_conditions.append(...)
                        pass

                if type_conditions:
                    stmt = stmt.where(or_(*type_conditions))

            # package filter
            if package:
                if "on-package" in package:
                    stmt = stmt.where(
                        exists().where(
                            PatientPackageAssignmentModel.patient_id
                            == PatientModel.patient_id
                        )
                    )
                if "no-package" in package:
                    stmt = stmt.where(
                        ~exists().where(
                            PatientPackageAssignmentModel.patient_id
                            == PatientModel.patient_id
                        )
                    )

            # connected apps filter (e.g., libreview)
            if connected_apps:
                stmt = stmt.outerjoin(PatientModel.connected_apps)

                app_conditions = []

                for app in connected_apps:
                    if app == "libreview":
                        app_conditions.append(
                            PatientConnectedApp.libreview != None
                        )

                    if app == "sinocare":
                        app_conditions.append(
                            PatientConnectedApp.sinocare != None
                        )

                if app_conditions:
                    stmt = stmt.where(or_(*app_conditions))

            stmt = stmt.order_by(PatientModel.created_at.desc())

            result = await postgres_session.execute(stmt)
            patients = list(result.scalars().all())

            return patients

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def fetch_care_providers(
        self,
        health_facility_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        *,
        postgres_session: AsyncSession,
    ) -> List[CareProviderModel]:
        try:
            stmt = select(CareProviderModel).options(
                selectinload(CareProviderModel.health_facility),
                selectinload(CareProviderModel.patients),
                selectinload(CareProviderModel.packages),
            )

            if health_facility_id:
                stmt = stmt.where(
                    CareProviderModel.health_facility_id == health_facility_id
                )

            if offset:
                stmt = stmt.offset(offset)
            
            if limit:
                stmt = stmt.limit(limit)

            result = await postgres_session.execute(stmt)
            care_providers = result.scalars().all()

            return list(care_providers)

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def count_care_providers(
        self,
        health_facility_id: Optional[str] = None,
        *,
        postgres_session: AsyncSession,
    ) -> int:
        try:
            stmt = select(func.count(distinct(CareProviderModel.care_provider_id)))

            if health_facility_id:
                stmt = stmt.where(
                    CareProviderModel.health_facility_id == health_facility_id
                )

            result = await postgres_session.execute(stmt)
            count = result.scalar() or 0

            return count

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def fetch_care_provider_by_code(
        self, code: str, *, postgres_session: AsyncSession
    ) -> CareProviderModel:
        try:
            CODE_PATTERN = re.compile(r"^[A-Za-z0-9-]{6}$")

            # Validate code format (6 uppercase alphanumeric characters)
            if not (len(code) == 6 and CODE_PATTERN.match(code)):
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Invalid code.",
                )

            stmt = (
                select(CareProviderModel)
                .where(CareProviderModel.code == code)
                .options(
                    selectinload(CareProviderModel.health_facility),
                )
            )
            result = await postgres_session.execute(stmt)
            care_provider = result.scalars().first()

            if not care_provider:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Care provider not found with the provided code.",
                )

            return care_provider

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def generate_unique_code(
        self, *, postgres_session: AsyncSession
    ) -> str:
        while True:
            code = "".join(
                random.choices(string.ascii_uppercase + string.digits, k=6)
            )
            stmt = select(CareProviderModel).where(
                CareProviderModel.code == code
            )
            result = await postgres_session.execute(stmt)
            if not result.scalars().first():
                return code

    @with_postgres_session
    async def create_care_provider(
        self,
        care_provider_data: CareProviderCreate,
        health_facility_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> (
        CareProviderModel
    ):  # TODO: fix validation on invalid health_facility id
        try:
            # Convert role to enum and get permissions
            role_enum = CareProviderRole(care_provider_data.role.lower())
            permissions = get_care_provider_permissions(role_enum)
            care_provider_data.permissions = permissions
            code = await self.generate_unique_code(postgres_session=postgres_session)  # type: ignore

            new_care_provider = CareProviderModel(
                **care_provider_data.model_dump(),
                code=code,
                health_facility_id=health_facility_id,
            )

            postgres_session.add(new_care_provider)
            await postgres_session.commit()
            await postgres_session.refresh(new_care_provider)

            return new_care_provider

        except IntegrityError:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Care provider already exists",
            )

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def update_care_provider(
        self,
        care_provider_id: str,
        updates: CareProviderUpdate,
        *,
        postgres_session: AsyncSession,
    ) -> CareProviderModel:
        try:
            care_provider_profile = await self.fetch_care_provider(
                care_provider_id, postgres_session=postgres_session
            )

            # Create filtered updates dict
            update_data = updates.model_dump(exclude_unset=True)
            restricted_fields = {"phone_number", "role", "permissions"}
            filtered_updates = {
                k: v
                for k, v in update_data.items()
                if k not in restricted_fields
            }

            # Apply only filtered updates
            for key, value in filtered_updates.items():
                setattr(care_provider_profile, key, value)

            postgres_session.add(care_provider_profile)
            await postgres_session.commit()
            await postgres_session.refresh(care_provider_profile)

            await self.chat_notification_service.notify_participants(
                message_key=EmitMessageKeyEnum.CHAT_LIST_UPDATED.value,
                user_id=care_provider_id,
            )
            return care_provider_profile

        except IntegrityError:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Care provider already exists.",
            )

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def delete_care_provider(
        self, care_provider_id: str, *, postgres_session: AsyncSession
    ):
        try:
            care_provider = await self.fetch_care_provider(
                care_provider_id, postgres_session=postgres_session
            )

            await postgres_session.delete(care_provider)
            await postgres_session.commit()

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def check_care_provider_exists(
        self, care_provider_id: str, *, postgres_session: AsyncSession
    ) -> bool:
        try:
            stmt = select(
                exists().where(
                    CareProviderModel.care_provider_id == care_provider_id
                )
            )
            result = await postgres_session.execute(stmt)
            (exists_result,) = result.scalars()

            if not exists_result:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Care provider not found.",
                )

            return True
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def set_care_provider_password(
        self,
        care_provider_id: str,
        raw_password: str,
        *,
        postgres_session: AsyncSession,
    ) -> CareProviderModel:
        try:
            care_provider_profile = await self.fetch_care_provider(
                care_provider_id, postgres_session=postgres_session
            )

            if care_provider_profile.email is None:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Email is required to set a password",
                )

            hashed_password = hash_password(raw_password)

            care_provider_profile.hashed_password = hashed_password  # type: ignore
            postgres_session.add(care_provider_profile)

            await postgres_session.commit()
            await postgres_session.refresh(care_provider_profile)

            return care_provider_profile

        except IntegrityError:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Failed to set password due to a database conflict.",
            )

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def authenticate_care_provider(
        self, email: str, password: str, *, postgres_session: AsyncSession
    ) -> CareProviderModel:
        try:
            stmt = select(CareProviderModel).where(
                CareProviderModel.email == email
            )
            result = await postgres_session.execute(stmt)
            care_provider = result.scalars().first()

            if not care_provider:
                raise_http_exception(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    message="Invalid email or password.",
                )

            if not care_provider.hashed_password:  # type: ignore
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Password not set. Please set your password to log in.",
                )

            if not verify_password(
                password, str(care_provider.hashed_password)
            ):
                raise_http_exception(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    message="Invalid email or password",
                )

            return care_provider

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def update_care_provider_permissions(
        self,
        care_provider_id: str,
        permissions_update: Dict[str, PermissionActionSchema],
        *,
        postgres_session: AsyncSession,
    ) -> CareProviderModel:
        try:
            care_provider = await self.fetch_care_provider(
                care_provider_id, postgres_session=postgres_session
            )

            # Directly update permissions
            care_provider.permissions = {  # type: ignore
                feature: action.model_dump()
                for feature, action in permissions_update.items()
            }
            flag_modified(care_provider, "permissions")

            postgres_session.add(care_provider)
            await postgres_session.commit()
            await postgres_session.refresh(care_provider)

            return care_provider

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )
