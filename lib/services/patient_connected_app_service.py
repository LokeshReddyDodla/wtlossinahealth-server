from datetime import datetime
from typing import Any, List

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.models.patient_connected_app import \
    PatientConnectedApp as PatientConnectedAppModel
from lib.models.patient_connected_app import \
    PatientLibreView as PatientLibreViewModel
from lib.schemas.patient_connected_app import PatientLibreViewCreate
from lib.utils.http_exceptions import raise_http_exception


class PatientConnectedAppService:
    def __init__(self, postgres_session: AsyncSession):
        self.postgres_session = postgres_session

    async def get_connected_apps_for_patient(
        self, patient_id: str
    ) -> PatientConnectedAppModel:
        try:
            result = await self.postgres_session.execute(
                select(PatientConnectedAppModel)
                .where(PatientConnectedAppModel.patient_id == patient_id)
                .options(selectinload(PatientConnectedAppModel.libreview))
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

    async def get_all_connected_apps_with_libreview(
        self,
    ) -> List[PatientConnectedAppModel]:
        try:
            result = await self.postgres_session.execute(
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

    async def add_or_update_libreview(
        self, patient_id: str, libreview_data: PatientLibreViewCreate
    ) -> PatientLibreViewModel:
        try:
            connected_app = await self.get_connected_apps_for_patient(
                patient_id
            )

            result = await self.postgres_session.execute(
                select(PatientLibreViewModel).where(
                    PatientLibreViewModel.connected_app_id == connected_app.id,
                )
            )
            existing_libreview: Any = result.scalars().first()

            if existing_libreview:
                # Update existing LibreView record
                existing_libreview.libreview_id = libreview_data.libreview_id
                existing_libreview.last_sync_timestamp = None

                await self.postgres_session.commit()
                await self.postgres_session.refresh(existing_libreview)
                return existing_libreview
            else:
                # Create new LibreView record
                new_libreview = PatientLibreViewModel(
                    connected_app_id=connected_app.id,
                    libreview_id=libreview_data.libreview_id,
                )

                self.postgres_session.add(new_libreview)
                await self.postgres_session.commit()
                await self.postgres_session.refresh(new_libreview)
                return new_libreview

        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=f"Failed to add or update LibreView data for patient ID '{patient_id}'.",
                detail=str(e),
            )
