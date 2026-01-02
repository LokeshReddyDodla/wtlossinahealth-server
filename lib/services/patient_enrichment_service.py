from lib.services.cgm_report_service import CGMReportService
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
        include_cgm: bool,
        include_last_active: bool,
    ):
        user_ids = [str(p.patient_id) for p in patients]

        cgm_map = {}
        last_active_map = {}

        if include_cgm:
            cgm_map = await self.cgm_service.fetch_reports_batch(user_ids)

        if include_last_active:
            last_active_map = await self.user_device_service.get_last_active_map(
                user_ids,
                profile_type=ProfileTypeEnum.PATIENT.value,
            )

        return cgm_map, last_active_map
