import uuid
from sqlalchemy import UUID, Boolean, Column, ForeignKey, Integer, String, Text
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientPrescription(Base):
    __tablename__ = "patient_prescriptions"

    prescription_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    medication_id = Column(
        UUID(as_uuid=True), ForeignKey("patient_current_medication.medication_id")
    )
    prescription_file = Column(Text)
