from sqlalchemy import UUID, Column, ForeignKey, Table

from lib.models import Base

patient_care_provider_association = Table(
    "patient_care_provider_association",
    Base.metadata,
    Column(
        "patient_id",
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "care_provider_id",
        ForeignKey("care_providers.care_provider_id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

package_care_provider_association = Table(
    "package_care_provider_association",
    Base.metadata,
    Column(
        "package_id",
        ForeignKey("packages.package_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "care_provider_id",
        ForeignKey("care_providers.care_provider_id", ondelete="CASCADE"),
        primary_key=True,
    ),
)
