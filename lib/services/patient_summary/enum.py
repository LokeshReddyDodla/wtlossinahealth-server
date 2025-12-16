from enum import Enum


class StaleReason(str, Enum):
    DATA_UPLOADED = "data_uploaded"
    DATA_UPDATED = "data_updated"
    DATA_DELETED = "data_deleted"
    DEVICE_SYNCED = "device_synced"
    MANUAL_EDIT = "manual_edit"
    SYSTEM_CORRECTION = "system_correction"


class SummaryState(str, Enum):
    FINALIZED = "finalized"
    STALE = "stale"


class RegeneratedBy(str, Enum):
    SYSTEM = "system"
    USER = "user"