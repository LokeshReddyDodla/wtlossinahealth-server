"""Templates for CGM report sections."""

from datetime import datetime
from typing import Dict, Any


class CGMSectionTemplates:
    """Templates for different report sections with unit suffix naming for reliability."""

    @staticmethod
    def cgm_range_stats(
        start_str: str, end_str: str, data: Dict[str, Any]
    ) -> str:
        return (
            f"CGM range stats from {start_str} to {end_str}: "
            f"time_in_range_70_180_percent: {data.get('in_target_70_180_percent', 0):.2f}%, "
            f"time_in_tight_range_70_140_percent: {data.get('in_tight_target_70_140_percent', 0):.2f}%, "
            f"time_above_180_250_percent: {data.get('above_180_below_250_percent', 0):.2f}%, "
            f"time_above_250_percent: {data.get('above_250_percent', 0):.2f}%, "
            f"time_below_70_54_percent: {data.get('below_70_above_54_percent', 0):.2f}%, "
            f"time_below_54_percent: {data.get('below_54_percent', 0):.2f}%."
        )

    @staticmethod
    def cgm_summary_stats(start_str: str, end_str: str, data: dict) -> str:
        return (
            f"CGM summary stats from {start_str} to {end_str}: "
            f"average_glucose_mgdl: {data.get('average_glucose_mgdl', 0):.2f}, "
            f"GMI: {data.get('gmi', 0):.2f}, "
            f"glycemia_risk_index: {data.get('gri', 0):.1f}, "
            f"glucose_variability_percent: {data.get('glucose_variability_percent', 0):.2f}%, "
            f"nocturnal_time_below_70_percent: {data.get('nocturnal_time_below_70_percent', 0):.2f}%, "
            f"dawn_rise_mgdl: {data.get('dawn_rise_mgdl', 0):.1f}, "
            f"std_dev_glucose_mgdl: {data.get('std_dev_glucose_mgdl', 0):.2f}, "
            f"highest_glucose_mgdl: {data.get('highest_glucose_mgdl', 0)} "
            f"on {data.get('highest_glucose_date', 'N/A')}, "
            f"lowest_glucose_mgdl: {data.get('lowest_glucose_mgdl', 0)} "
            f"on {data.get('lowest_glucose_date', 'N/A')}."
        )

    @staticmethod
    def hyper_stats(start_str: str, end_str: str, data: dict) -> str:
        return (
            f"Hyperglycemia stats from {start_str} to {end_str}: "
            f"total_duration_minutes: {data.get('total_hyper_duration_minutes', 0)}, "
            f"hyper_events_count: {data.get('hyper_events_count', 0)}, "
            f"average_duration_minutes: {data.get('average_hyper_duration_minutes', 0):.2f}."
        )

    @staticmethod
    def hypo_stats(start_str: str, end_str: str, data: dict) -> str:
        return (
            f"Hypoglycemia stats from {start_str} to {end_str}: "
            f"total_duration_minutes: {data.get('total_hypo_duration_minutes', 0)}, "
            f"hypo_events_count: {data.get('hypo_events_count', 0)}, "
            f"average_duration_minutes: {data.get('average_hypo_duration_minutes', 0):.2f}."
        )

    @staticmethod
    def hyper_event(event: dict) -> str:
        return (
            f"Hyper event: start_time: {event['start_time']}, end_time: {event['end_time']}, "
            f"duration_minutes: {event['duration_minutes']}, peak_glucose_mgdl: {event['peak_glucose_mgdl']}."
        )

    @staticmethod
    def hypo_event(event: dict) -> str:
        return (
            f"Hypo event: start_time: {event['start_time']}, end_time: {event['end_time']}, "
            f"duration_minutes: {event['duration_minutes']}, lowest_glucose_mgdl: {event['lowest_glucose_mgdl']}."
        )

    @staticmethod
    def rapid_spike_stats(start_str: str, end_str: str, data: dict) -> str:
        return (
            f"Rapid spike stats from {start_str} to {end_str}: "
            f"total_spike_duration_minutes: {data.get('total_spike_duration_minutes', 0)}, "
            f"spike_events_count: {data.get('spike_events_count', 0)}, "
            f"average_spike_duration_minutes: {data.get('average_spike_duration_minutes', 0):.2f}."
        )

    @staticmethod
    def rapid_spike_event(event: dict) -> str:
        return (
            f"Rapid spike event: start_time: {event['start_time']}, end_time: {event['end_time']}, "
            f"duration_minutes: {event['duration_minutes']}, initial_glucose_mgdl: {event['initial_glucose_mgdl']}, "
            f"peak_glucose_mgdl: {event['peak_glucose_mgdl']} at {event.get('peak_glucose_time', 'N/A')}."
        )

    @staticmethod
    def rapid_drop_stats(start_str: str, end_str: str, data: dict) -> str:
        return (
            f"Rapid drop stats from {start_str} to {end_str}: "
            f"total_drop_duration_minutes: {data.get('total_drop_duration_minutes', 0)}, "
            f"drop_events_count: {data.get('drop_events_count', 0)}, "
            f"average_drop_duration_minutes: {data.get('average_drop_duration_minutes', 0):.2f}."
        )

    @staticmethod
    def rapid_drop_event(event: dict) -> str:
        return (
            f"Rapid drop event: start_time: {event['start_time']}, end_time: {event['end_time']}, "
            f"duration_minutes: {event['duration_minutes']}, initial_glucose_mgdl: {event['initial_glucose_mgdl']}, "
            f"lowest_glucose_mgdl: {event['lowest_glucose_mgdl']} at {event.get('lowest_glucose_time', 'N/A')}."
        )

    @staticmethod
    def time_period_stats(
        period_name: str, start_time: datetime, end_time: datetime, data: dict
    ) -> str:
        return (
            f"{period_name} period from {start_time.date()} to {end_time.date()}: "
            f"average_glucose_mgdl: {data.get('average_glucose_mgdl', 0):.2f}, "
            f"highest_glucose_mgdl: {data.get('highest_glucose_mgdl', 0)}, "
            f"lowest_glucose_mgdl: {data.get('lowest_glucose_mgdl', 0)}, "
            f"out_of_range_percent: {data.get('out_of_range_percent', 0):.2f}%, "
            f"from_time: {data.get('from_time')}, to_time: {data.get('to_time')}."
        )

    @staticmethod
    def agp_point(start_str: str, end_str: str, point: dict) -> str:
        return (
            f"AGP point for hour: {point.get('hour')}, "
            f"median_mgdl: {point.get('median_mgdl', 0)}, "
            f"percentile_10_mgdl: {point.get('percentile_10_mgdl', 0)}, "
            f"percentile_25_mgdl: {point.get('percentile_25_mgdl', 0)}, "
            f"percentile_75_mgdl: {point.get('percentile_75_mgdl', 0)}, "
            f"percentile_90_mgdl: {point.get('percentile_90_mgdl', 0)}, "
            f"report_period: {start_str} to {end_str}."
        )

    @staticmethod
    def cgm_semantic_window(
        start_str: str, end_str: str, data: dict
    ) -> str:
        return (
            f"CGM semantic window from {start_str} to {end_str}: "
            f"readings_count: {data.get('readings_count', 0)}, "
            f"min_glucose_mgdl: {data.get('min_glucose_mgdl', 0)}, "
            f"avg_glucose_mgdl: {data.get('avg_glucose_mgdl', 0):.2f}, "
            f"max_glucose_mgdl: {data.get('max_glucose_mgdl', 0)}."
        )

    @staticmethod
    def default_section(
        section_name: str, start_str: str, end_str: str, data: dict
    ) -> str:
        return f"{section_name} data from {start_str} to {end_str}: {data}"
