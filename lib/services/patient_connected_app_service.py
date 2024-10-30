from typing import List

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
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="ConnectedApp instance not found",
                )
            return connected_app
        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
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
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )

    async def add_libreview(
        self, patient_id: str, libreview_data: PatientLibreViewCreate
    ) -> PatientLibreViewModel:
        try:
            # Get connected app
            connected_app = await self.get_connected_apps_for_patient(
                patient_id
            )

            # Add new LibreView
            new_libreview = PatientLibreViewModel(
                connected_app_id=connected_app.id,
                libreview_id=libreview_data.libreview_id,
            )
            self.postgres_session.add(new_libreview)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(new_libreview)

            return new_libreview

        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )
