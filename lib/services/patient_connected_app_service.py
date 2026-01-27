from datetime import datetime
from typing import Any, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.core.postgres_store import PostgresStore
from lib.models.patient_connected_app import (
    PatientConnectedApp as PatientConnectedAppModel,
)
from lib.models.patient_connected_app import (
    PatientLibreView as PatientLibreViewModel,
)
from lib.models.patient_connected_app import (
    PatientSinocare as PatientSinocareModel,
)
from lib.schemas.patient_connected_app import PatientLibreViewCreate
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session


class PatientConnectedAppService:
    def __init__(
        self,
        postgres_store: PostgresStore,
    ):
        self.postgres_store = postgres_store

    @with_postgres_session
    async def get_connected_apps_for_patient(
        self, patient_id: str, *, postgres_session: AsyncSession
    ) -> PatientConnectedAppModel:
        try:
            result = await postgres_session.execute(
                select(PatientConnectedAppModel)
                .where(PatientConnectedAppModel.patient_id == patient_id)
                .options(
                    selectinload(PatientConnectedAppModel.libreview),
                    selectinload(PatientConnectedAppModel.sinocare),
                )
            )

            connected_app = result.scalars().first()
            if not connected_app:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=f"Connected apps for patient ID '{patient_id}' not found.",
                )
            return connected_app
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=f"Failed to retrieve connected apps for patient ID '{patient_id}'.",
                detail=str(e),
            )

    @with_postgres_session
    async def get_all_connected_apps_with_libreview(
        self, *, postgres_session: AsyncSession
    ) -> List[PatientConnectedAppModel]:
        try:
            result = await postgres_session.execute(
                select(PatientConnectedAppModel)
                .where(PatientConnectedAppModel.libreview != None)
                .options(
                    selectinload(PatientConnectedAppModel.libreview),
                    selectinload(PatientConnectedAppModel.patient),
                )
            )

            connected_apps = list(result.scalars().all())
            return connected_apps
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to retrieve all connected apps with LibreView data.",
                detail=str(e),
            )

    @with_postgres_session
    async def get_all_connected_apps_with_sinocare(
        self, *, postgres_session: AsyncSession
    ) -> List[PatientConnectedAppModel]:
        try:
            result = await postgres_session.execute(
                select(PatientConnectedAppModel)
                .where(PatientConnectedAppModel.sinocare != None)
                .options(
                    selectinload(PatientConnectedAppModel.sinocare),
                    selectinload(PatientConnectedAppModel.patient),
                )
            )

            connected_apps = list(result.scalars().all())
            return connected_apps
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to retrieve all connected apps with sinocare data.",
                detail=str(e),
            )

    @with_postgres_session
    async def add_or_update_libreview(
        self,
        patient_id: str,
        libreview_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> PatientLibreViewModel:
        try:
            connected_app = await self.get_connected_apps_for_patient(
                patient_id, postgres_session=postgres_session
            )

            result = await postgres_session.execute(
                select(PatientLibreViewModel).where(
                    PatientLibreViewModel.connected_app_id == connected_app.id,
                )
            )
            existing_libreview: Any = result.scalars().first()

            if existing_libreview:
                if existing_libreview.libreview_id != libreview_id:
                    existing_libreview.last_sync_timestamp = None
                existing_libreview.libreview_id = libreview_id

                await postgres_session.commit()
                await postgres_session.refresh(existing_libreview)
                return existing_libreview
            else:
                # Create new LibreView record
                new_libreview = PatientLibreViewModel(
                    connected_app_id=connected_app.id,
                    libreview_id=libreview_id,
                )

                postgres_session.add(new_libreview)
                await postgres_session.commit()
                await postgres_session.refresh(new_libreview)
                return new_libreview

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=f"Failed to add or update LibreView data for patient ID '{patient_id}'.",
                detail=str(e),
            )

    @with_postgres_session
    async def add_or_update_sinocare(
        self,
        patient_id: str,
        sinocare_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> PatientSinocareModel:
        try:
            connected_app = await self.get_connected_apps_for_patient(
                patient_id, postgres_session=postgres_session
            )

            result = await postgres_session.execute(
                select(PatientSinocareModel).where(
                    PatientSinocareModel.connected_app_id == connected_app.id,
                )
            )
            existing_sinocare: Any = result.scalars().first()

            if existing_sinocare:
                # Update existing sinocare record
                existing_sinocare.sinocare_id = sinocare_id
                existing_sinocare.last_sync_timestamp = None

                await postgres_session.commit()
                await postgres_session.refresh(existing_sinocare)
                return existing_sinocare
            else:
                # Create new sinocare record
                new_sinocare = PatientSinocareModel(
                    connected_app_id=connected_app.id,
                    sinocare_id=sinocare_id,
                )

                postgres_session.add(new_sinocare)
                await postgres_session.commit()
                await postgres_session.refresh(new_sinocare)
                return new_sinocare

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=f"Failed to add or update sinocare data for patient ID '{patient_id}'.",
                detail=str(e),
            )

    @with_postgres_session
    async def remove_libreview(
        self,
        patient_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> None:

        try:
            connected_app = await self.get_connected_apps_for_patient(
                patient_id, postgres_session=postgres_session
            )

            result = await postgres_session.execute(
                select(PatientLibreViewModel).where(
                    PatientLibreViewModel.connected_app_id == connected_app.id,
                )
            )
            libreview: Optional[PatientLibreViewModel] = (
                result.scalars().first()
            )

            if not libreview:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=f"No LibreView account found for patient ID '{patient_id}'.",
                )

            await postgres_session.delete(libreview)
            await postgres_session.commit()

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=f"Failed to unlink LibreView for patient ID '{patient_id}'.",
                detail=str(e),
            )

    @with_postgres_session
    async def remove_sinocare(
        self,
        patient_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> None:

        try:
            connected_app = await self.get_connected_apps_for_patient(
                patient_id, postgres_session=postgres_session
            )

            result = await postgres_session.execute(
                select(PatientSinocareModel).where(
                    PatientSinocareModel.connected_app_id == connected_app.id,
                )
            )
            sinocare: Optional[PatientSinocareModel] = result.scalars().first()

            if not sinocare:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=f"No Sinocare account found for patient ID '{patient_id}'.",
                )

            await postgres_session.delete(sinocare)
            await postgres_session.commit()

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=f"Failed to unlink sinocare for patient ID '{patient_id}'.",
                detail=str(e),
            )
