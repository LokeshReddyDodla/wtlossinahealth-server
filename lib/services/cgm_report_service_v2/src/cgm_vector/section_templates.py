from datetime import datetime
from typing import Dict, Any


class CGMSectionTemplates:
    """Templates for different report sections"""

    @staticmethod
    def cgm_range_stats(
        patient_id: str, start_str: str, end_str: str, data: Dict[str, Any]
    ) -> str:
        return (
            f"Patient {patient_id} CGM range stats from {start_str} to {end_str}: "
            f"{data.get('in_target_70_180', 0):.2f}% time in range (70–180), "
            f"{data.get('above_180_below_250', 0):.2f}% above 180–250, "
            f"{data.get('above_250', 0):.2f}% above 250, "
            f"{data.get('below_70_above_54', 0):.2f}% below 70–54, "
            f"{data.get('below_54', 0):.2f}% below 54."
        )

    @staticmethod
    def cgm_summary_stats(
        patient_id: str, start_str: str, end_str: str, data: dict
    ) -> str:
        return (
            f"Patient {patient_id} CGM summary stats from {start_str} to {end_str}: "
            f"average glucose {data.get('average_glucose', 0):.2f}, "
            f"GMI {data.get('gmi', 0):.2f}, "
            f"variability {data.get('glucose_variability', 0):.2f}, "
            f"standard deviation {data.get('standard_deviation', 0):.2f}, "
            f"highest glucose {data.get('highest_glucose', 0)} "
            f"on {data.get('highest_glucose_date', 'N/A')}, "
            f"lowest glucose {data.get('lowest_glucose', 0)} "
            f"on {data.get('lowest_glucose_date', 'N/A')}."
        )

    @staticmethod
    def hyper_stats(
        patient_id: str, start_str: str, end_str: str, data: dict
    ) -> str:
        return (
            f"Patient {patient_id} hyperglycemia stats from {start_str} to {end_str}: "
            f"total hyper duration {data.get('total_hyper_duration', 0)} mins, "
            f"{data.get('hyper_events_count', 0)} events, "
            f"average hyper duration {data.get('average_hyper_duration', 0):.2f} mins."
        )

    @staticmethod
    def hypo_stats(
        patient_id: str, start_str: str, end_str: str, data: dict
    ) -> str:
        return (
            f"Patient {patient_id} hypoglycemia stats from {start_str} to {end_str}: "
            f"total hypo duration {data.get('total_hypo_duration', 0)} mins, "
            f"{data.get('hypo_events_count', 0)} events, "
            f"average hypo duration {data.get('average_hypo_duration', 0):.2f} mins."
        )

    @staticmethod
    def hyper_event(patient_id: str, event: dict) -> str:
        return (
            f"Patient {patient_id} hyper event: "
            f"start {event['start_time']}, end {event['end_time']}, "
            f"duration {event['duration']} minutes, "
            f"peak glucose {event['peak_glucose_level']}."
        )

    @staticmethod
    def hypo_event(patient_id: str, event: dict) -> str:
        return (
            f"Patient {patient_id} hypo event: "
            f"start {event['start_time']}, end {event['end_time']}, "
            f"duration {event['duration']} minutes, "
            f"lowest glucose {event['lowest_glucose_level']}."
        )

    @staticmethod
    def rapid_spike_stats(
        patient_id: str, start_str: str, end_str: str, data: dict
    ) -> str:
        return (
            f"Patient {patient_id} rapid spike stats from {start_str} to {end_str}: "
            f"total spike duration {data.get('total_spike_duration', 0)} mins, "
            f"{data.get('spike_events_count', 0)} events, "
            f"average spike duration {data.get('average_spike_duration', 0):.2f} mins."
        )

    @staticmethod
    def rapid_spike_event(patient_id: str, event: dict) -> str:
        return (
            f"Patient {patient_id} rapid spike event: "
            f"start {event['start_time']}, end {event['end_time']}, "
            f"duration {event['duration']} mins, "
            f"initial glucose {event['initial_glucose_level']}, "
            f"peak glucose {event['peak_glucose_level']} at {event.get('peak_glucose_time')}."
        )

    @staticmethod
    def rapid_drop_stats(
        patient_id: str, start_str: str, end_str: str, data: dict
    ) -> str:
        return (
            f"Patient {patient_id} rapid drop stats from {start_str} to {end_str}: "
            f"total drop duration {data.get('total_drop_duration', 0)} mins, "
            f"{data.get('drop_events_count', 0)} events, "
            f"average drop duration {data.get('average_drop_duration', 0):.2f} mins."
        )

    @staticmethod
    def rapid_drop_event(patient_id: str, event: dict) -> str:
        return (
            f"Patient {patient_id} rapid drop event: "
            f"start {event['start_time']}, end {event['end_time']}, "
            f"duration {event['duration']} mins, "
            f"initial glucose {event['initial_glucose_level']}, "
            f"lowest glucose {event['lowest_glucose_level']} "
            f"at {event.get('lowest_glucose_time', 'N/A')}."
        )

    @staticmethod
    def time_period_stats(
        patient_id: str,
        period_name: str,
        start_time: datetime,
        end_time: datetime,
        data: dict,
    ) -> str:
        return (
            f"Patient {patient_id} {period_name} period "
            f"(from {start_time.date()} to {end_time.date()}): "
            f"average glucose {data.get('average_glucose', 0):.2f}, "
            f"highest glucose {data.get('highest_glucose', 0)}, "
            f"lowest glucose {data.get('lowest_glucose', 0)}, "
            f"out-of-range percentage {data.get('out_of_range_percentage', 0):.2f}%, "
            f"from {data.get('from_time')} to {data.get('to_time')}."
        )

    @staticmethod
    def agp_point(
        patient_id: str, start_str: str, end_str: str, point: dict
    ) -> str:
        return (
            f"Patient {patient_id} AGP point for {point.get('hour')}: "
            f"median {point.get('median', 0)}, tenth percentile {point.get('tenth_percentile', 0)}, "
            f"ninetieth percentile {point.get('ninetieth_percentile', 0)}, "
            f"25th percentile {point.get('twenty_fifth_percentile', 0)}, "
            f"75th percentile {point.get('seventy_fifth_percentile', 0)}, "
            f"report period from {start_str} to {end_str}."
        )

    @staticmethod
    def default_section(
        patient_id: str,
        section_name: str,
        start_str: str,
        end_str: str,
        data: dict,
    ) -> str:
        return f"Patient {patient_id} {section_name} data from {start_str} to {end_str}: {data}"
