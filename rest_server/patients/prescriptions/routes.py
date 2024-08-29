from fastapi import APIRouter
from analyze_prescription import router as analyze_prescription_router


router = APIRouter(prefix="/patient/prescriptions", tags=["Prescriptions"])

router.include_router(analyze_prescription_router)
