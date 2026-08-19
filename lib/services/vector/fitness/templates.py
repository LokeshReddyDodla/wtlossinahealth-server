"""Templates for Fitness report sections."""


class FitnessSectionTemplates:
    """Templates for Fitness report sections."""

    @staticmethod
    def fitness_overview(start_str: str, end_str: str, data: dict) -> str:
        trend = ""
        if data.get("delta_steps") is not None:
            trend = (
                f" trend vs previous period: {data.get('delta_steps'):+d} steps, "
                f"{data.get('delta_active_energy', 0):+.0f} active_energy, "
                f"{data.get('delta_active_duration', 0):+.0f} min active."
            )
        return (
            f"Fitness summary from {start_str} to {end_str}: "
            f"days_with_data: {data.get('days_with_data')}, "
            f"steps: {data.get('steps')}, "
            f"active_duration: {data.get('active_duration')} min, "
            f"active_energy: {data.get('active_energy')}, "
            f"average_active_session_duration: {data.get('average_active_session_duration')}, "
            f"peak activity hour: {data.get('peak_hour')} with {data.get('peak_steps')} steps."
            f"{trend}"
        )

    @staticmethod
    def fitness_activity_distribution(
        start_str: str, end_str: str, data: dict
    ) -> str:
        return (
            f"Activity distribution from {start_str} to {end_str}: "
            f"morning: {data.get('morning_steps')} steps, {data.get('morning_duration')} min active; "
            f"afternoon: {data.get('afternoon_steps')} steps, {data.get('afternoon_duration')} min active; "
            f"evening: {data.get('evening_steps')} steps, {data.get('evening_duration')} min active."
        )

    @staticmethod
    def fitness_inactive_period(event: dict) -> str:
        return (
            f"Inactive period: {event.get('inactive_duration')} minutes "
            f"from {event['start_time']} to {event['end_time']}."
        )
