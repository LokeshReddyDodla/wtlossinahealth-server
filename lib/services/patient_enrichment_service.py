from typing import Dict
from lib.services.reports import CGMReportService
from lib.services.user_device_service import UserDeviceService
from lib.models.patient import Patient as PatientModel
from lib.core.constants import ProfileTypeEnum


class PatientEnrichmentService:
    def __init__(
        self,
        cgm_service: CGMReportService,
        user_device_service: UserDeviceService,
    ):
        self.cgm_service = cgm_service
        self.user_device_service = user_device_service

    async def enrich(
        self,
        patients: list[PatientModel],
        
    ) -> dict[str, list[Dict]]:
        user_ids = [str(p.patient_id) for p in patients]

        enrichment = {
            "cgm": {},
            "last_active": {},
        }

        enrichment["cgm"] = await self.cgm_service.fetch_reports_batch(user_ids)

        enrichment["last_active"] = await self.user_device_service.get_last_active_map(
            user_ids,
            profile_type=ProfileTypeEnum.PATIENT.value,
        )

        return enrichment
