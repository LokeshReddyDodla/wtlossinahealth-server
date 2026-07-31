import uuid
from datetime import datetime

from sqlalchemy import (
    UUID,
    Boolean,
    Column,
    DateTime,
    Index,
    String,
    Text,
    text,
)

from lib.models import Base


class AIFeatureToggle(Base):
    """AI feature pause switch. Opt-out model: a row exists only to turn a
    feature OFF for a scope; absence of a row means the feature is enabled.

    scope='system' is global and stores scope_id = NULL (one row per feature).
    scope='facility' stores scope_id = health_facility_id.

    Effective state for a patient = system row (if any) AND that patient's
    facility row (if any) must both be enabled. Enforced at each agent entry
    point via AIFeatureToggleService, not here.
    """

    __tablename__ = "ai_feature_toggles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope = Column(String(16), nullable=False)  # AIToggleScopeEnum
    scope_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    feature = Column(String(40), nullable=False)  # AIFeatureEnum
    enabled = Column(Boolean, nullable=False, default=True)
    reason = Column(Text, nullable=True)
    updated_by = Column(UUID(as_uuid=True), nullable=True)  # admin id

    created_at = Column(DateTime, default=lambda: datetime.now().replace(tzinfo=None))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )

    # NULLs are distinct in a plain UNIQUE, so the system-scope uniqueness (one
    # row per feature) needs a partial index keyed on feature alone.
    __table_args__ = (
        Index(
            "uq_ai_toggle_system",
            "feature",
            unique=True,
            postgresql_where=text("scope = 'system'"),
        ),
        Index(
            "uq_ai_toggle_facility",
            "scope_id",
            "feature",
            unique=True,
            postgresql_where=text("scope = 'facility'"),
        ),
    )
