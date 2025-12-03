class FitnessSectionTemplates:

    @staticmethod
    def fitness_overview(start_str: str, end_str: str, data: dict) -> str:
        return (
            f"Fitness summary from {start_str} to {end_str}: "
            f"steps: {data.get('steps')}, "
            f"active_duration: {data.get('active_duration')} min, "
            f"active_energy: {data.get('active_energy')}, "
            f"average_active_session_duration: {data.get('average_active_session_duration')}, "
            f"peak activity hour: {data.get('peak_hour')} with {data.get('peak_steps')} steps."
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
