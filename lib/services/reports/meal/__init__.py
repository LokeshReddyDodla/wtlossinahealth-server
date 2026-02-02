"""Meal report service package."""

from .service import MealReportService
from .processor import MealStatsProcessor

__all__ = [
    "MealReportService",
    "MealStatsProcessor",
]
