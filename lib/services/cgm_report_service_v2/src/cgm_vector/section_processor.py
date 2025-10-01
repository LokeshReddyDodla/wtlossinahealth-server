from typing import Tuple, Dict
from datetime import datetime

from lib.services.cgm_report_service_v2.src.cgm_vector.section_configs import (
    get_section_config,
)
from lib.services.cgm_report_service_v2.src.cgm_vector.section_templates import (
    CGMSectionTemplates,
)


class CGMSectionProcessor:
    """Processes CGM report sections into text summaries and payloads"""

    @classmethod
    def generate_section_summary(
        cls,
        patient_id: str,
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
            summary_text = template_method(patient_id, section_data)  # type: ignore
        else:
            summary_text = template_method(
                patient_id, start_str, end_str, section_data
            )  # type: ignore

        # Create payload using section config keys
        payload = {
            key: section_data.get(key)
            for key in section_config.keys
            if key in section_data
        }

        return summary_text, payload
