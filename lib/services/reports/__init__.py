"""Report services package for patient data reports."""

from .cgm.service import CGMReportService
from .cgm.processor import CGMStatsProcessor, CGMReportType

from .meal.service import MealReportService
from .meal.processor import MealStatsProcessor

from .fitness.service import FitnessReportService
from .fitness.processor import FitnessStatsProcessor, FitnessReportType

from .sleep.service import SleepReportService
from .sleep.processor import SleepStatsProcessor, SleepReportType

from .smbg.processor import SMBGStatsProcessor

__all__ = [
    "CGMReportService",
    "CGMStatsProcessor",
    "CGMReportType",
    "MealReportService",
    "MealStatsProcessor",
    "FitnessReportService",
    "FitnessStatsProcessor",
    "FitnessReportType",
    "SleepReportService",
    "SleepStatsProcessor",
    "SleepReportType",
    "SMBGStatsProcessor",
]
