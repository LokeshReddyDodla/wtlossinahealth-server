from typing import Tuple, Dict
from datetime import datetime

from lib.services.cgm_vector_service.section_configs import (
    get_section_config,
)
from lib.services.cgm_vector_service.section_templates import (
    CGMSectionTemplates,
)


class CGMSectionProcessor:
    """Processes CGM report sections into text summaries and payloads"""

    @classmethod
    def generate_section_summary(
        cls,
        section_name: str,
        section_data: dict,
        start_time: datetime,
        end_time: datetime,
    ) -> Tuple[str, dict]:
        """Generate summary text and payload for any section"""

        start_str = start_time.isoformat()
        end_str = end_time.isoformat()

        # Get section configuration
        section_config = get_section_config(section_name)

        if not section_config:
            raise ValueError(
                f"No configuration found for section '{section_name}'"
            )

        # Get template method from ReportSectionTemplates
        template_method = getattr(
            CGMSectionTemplates,
            section_config.template_method,
            CGMSectionTemplates.default_section,
        )

        # Generate summary text
        if section_config.call_signature == "event":
            summary_text = template_method(section_data)  # type: ignore
        else:
            summary_text = template_method(
                start_str, end_str, section_data
            )  # type: ignore

        # Create payload using section config keys
        payload = {
            key: (
                int(value.timestamp() * 1000)
                if isinstance(value, datetime)
                else value
            )
            for key, value in section_data.items()
            if key in section_config.keys
        }

        return summary_text, payload
