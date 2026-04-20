"""Vector services package for patient data vectorization."""

from .base import BaseVectorService

# Import all vector services
from .cgm import CGMVectorService, CGMSectionProcessor, CGMSectionTemplates
from .fitness import FitnessVectorService, FitnessSectionProcessor, FitnessSectionTemplates
from .meal import MealVectorService, MealTextReprBuilder
from .smbg import SMBGVectorService, SMBGTextReprBuilder
from .profile import PatientProfileVectorService, PatientProfileTextReprBuilder
from .vitals import VitalsVectorService, VitalsTextReprBuilder
from .workout import WorkoutVectorService, WorkoutTextReprBuilder

__all__ = [
    "BaseVectorService",
    "CGMVectorService",
    "CGMSectionProcessor",
    "CGMSectionTemplates",
    "FitnessVectorService",
    "FitnessSectionProcessor",
    "FitnessSectionTemplates",
    "MealVectorService",
    "MealTextReprBuilder",
    "SMBGVectorService",
    "SMBGTextReprBuilder",
    "PatientProfileVectorService",
    "PatientProfileTextReprBuilder",
    "VitalsVectorService",
    "VitalsTextReprBuilder",
    "WorkoutVectorService",
    "WorkoutTextReprBuilder",
]
