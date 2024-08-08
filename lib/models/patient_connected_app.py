from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from lib.models import Base
import uuid
from datetime import datetime


class PatientConnectedApp(Base):
    __tablename__ = "patient_connected_apps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.patient_id"), nullable=False
    )

    patient = relationship("Patient", back_populates="connected_apps")
    libreview = relationship(
        "LibreView", back_populates="connected_app", uselist=False
    )
    other_app = relationship(
        "OtherApp", back_populates="connected_app", uselist=False
    )


class LibreView(Base):
    __tablename__ = "libreview"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connected_app_id = Column(
        UUID(as_uuid=True), ForeignKey("patient_connected_apps.id")
    )
    libreview_id = Column(String, nullable=False)
    last_sync_timestamp = Column(DateTime, nullable=True)
    connected_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )

    connected_app = relationship(
        "PatientConnectedApp", back_populates="libreview"
    )


class OtherApp(Base):
    __tablename__ = "other_app"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connected_app_id = Column(
        UUID(as_uuid=True), ForeignKey("patient_connected_apps.id")
    )
    other_app_id = Column(String, nullable=False)
    additional_field = Column(String, nullable=True)
    connected_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )

    connected_app = relationship(
        "PatientConnectedApp", back_populates="other_app"
    )
