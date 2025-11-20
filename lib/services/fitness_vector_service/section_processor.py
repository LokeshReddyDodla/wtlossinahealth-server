from datetime import datetime

from lib.services.fitness_vector_service.section_configs import (
    get_section_config,
)
from lib.services.fitness_vector_service.section_template import (
    FitnessSectionTemplates,
)


class FitnessSectionProcessor:

    @classmethod
    def generate_section_summary(
        cls,
        section_name: str,
        data: dict,
        start_time: datetime,
        end_time: datetime,
    ):
        start_str = start_time.isoformat()
        end_str = end_time.isoformat()

        # Get section configuration
        section_config = get_section_config(section_name)

        if not section_config:
            raise ValueError(
                f"No configuration found for section '{section_name}'"
            )

        template_method = getattr(
            FitnessSectionTemplates,
            section_config.template_method,
            FitnessSectionTemplates.fitness_overview,
        )

        # EVENT SECTION (inactive_period)
        if section_config.call_signature == "event":
            summary_text = template_method(data)  # type: ignore
        else:
            summary_text = template_method(start_str, end_str, data)

        # payload filtering
        payload = {
            k: (int(v.timestamp() * 1000) if isinstance(v, datetime) else v)
            for k, v in data.items()
            if k in section_config.keys
        }

        return summary_text, payload
