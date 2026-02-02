"""Fitness vector service package."""

from .service import FitnessVectorService
from .processor import FitnessSectionProcessor
from .templates import FitnessSectionTemplates
from .configs import STATS_CONFIGS

__all__ = [
    "FitnessVectorService",
    "FitnessSectionProcessor",
    "FitnessSectionTemplates",
    "STATS_CONFIGS",
]
