"""CGM vector service package."""

from .service import CGMVectorService
from .processor import CGMSectionProcessor
from .templates import CGMSectionTemplates
from .configs import (
    get_stats_section_names,
    get_section_config,
    CGMSectionConfig,
)

__all__ = [
    "CGMVectorService",
    "CGMSectionProcessor",
    "CGMSectionTemplates",
    "get_stats_section_names",
    "get_section_config",
    "CGMSectionConfig",
]
