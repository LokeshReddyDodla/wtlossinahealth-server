from datetime import datetime
import logging
from typing import Any, List, Optional, Tuple, cast
import uuid
from qdrant_client.models import PointStruct

from lib.core.qdrant_store import QdrantStore
from lib.utils.vector_utils import embed_text
from qdrant_client.http.models import (
    Filter,
    FieldCondition,
    MatchValue,
    MinShould,
    Condition,
)


logger = logging.getLogger(__name__)


def generate_section_summary(
    patient_id: str,
    section_name: str,
    section_data: dict,
    start_time: datetime,
    end_time: datetime,
) -> Tuple[str, dict]:
    start_str = start_time.isoformat()
    end_str = end_time.isoformat()

    if section_name == "cgm_range_stats":
        summary_text = (
            f"Patient {patient_id} CGM range stats from {start_str} to {end_str}: "
            f"{section_data.get('in_target_70_180', 0):.2f}% time in range (70–180), "
            f"{section_data.get('above_180_below_250', 0):.2f}% above 180–250, "
            f"{section_data.get('above_250', 0):.2f}% above 250, "
            f"{section_data.get('below_70_above_54', 0):.2f}% below 70–54, "
            f"{section_data.get('below_54', 0):.2f}% below 54."
        )

        keys = [
            "below_54",
            "below_70_above_54",
            "in_target_70_180",
            "above_180_below_250",
            "above_250",
        ]

    elif section_name == "cgm_summary_stats":
        summary_text = (
            f"Patient {patient_id} CGM summary stats from {start_str} to {end_str}: "
            f"average glucose {section_data.get('average_glucose', 0):.2f}, "
            f"GMI {section_data.get('gmi', 0):.2f}, "
            f"variability {section_data.get('glucose_variability', 0):.2f}, "
            f"standard deviation {section_data.get('standard_deviation', 0):.2f}, "
            f"highest glucose {section_data.get('highest_glucose', 0)} "
            f"on {section_data.get('highest_glucose_date', 'N/A')}, "
            f"lowest glucose {section_data.get('lowest_glucose', 0)} "
            f"on {section_data.get('lowest_glucose_date', 'N/A')}."
        )

        keys = [
            "average_glucose",
            "gmi",
            "glucose_variability",
            "standard_deviation",
            "highest_glucose",
            "highest_glucose_date",
            "lowest_glucose",
            "lowest_glucose_date",
        ]

    elif section_name == "hyper_stats":
        summary_text = (
            f"Patient {patient_id} hyperglycemia stats from {start_str} to {end_str}: "
            f"total hyper duration {section_data.get('total_hyper_duration', 0)} mins, "
            f"{section_data.get('hyper_events_count', 0)} events, "
            f"average hyper duration {section_data.get('average_hyper_duration', 0):.2f} mins."
        )

        keys = [
            "total_hyper_duration",
            "hyper_events_count",
            "average_hyper_duration",
        ]

    elif section_name == "hypo_stats":
        summary_text = (
            f"Patient {patient_id} hypoglycemia stats from {start_str} to {end_str}: "
            f"total hypo duration {section_data.get('total_hypo_duration', 0)} mins, "
            f"{section_data.get('hypo_events_count', 0)} events, "
            f"average hypo duration {section_data.get('average_hypo_duration', 0):.2f} mins."
        )

        keys = [
            "total_hypo_duration",
            "hypo_events_count",
            "average_hypo_duration",
        ]

    else:
        summary_text = f"Patient {patient_id} {section_name} data from {start_str} to {end_str}: {section_data}"
        keys = list(
            section_data.keys()
        )  # Use all keys for unknown section types

    payload = {key: section_data.get(key, 0.0) for key in keys}
    return summary_text, payload


class CGMReportVectorService:
    def __init__(
        self, qdrant_store: QdrantStore, collection_name: str = "patient_data"
    ):
        self.qdrant_store = qdrant_store
        self.collection_name = collection_name

    async def upsert_report(
        self,
        patient_id: str,
        report: Any,
    ):
        try:
            overall_report = report["overall"]
            report_id = overall_report["_id"]
            overview_start_time = overall_report["start_date"]
            overview_end_time = overall_report["end_date"]

            async with self.qdrant_store.get_client() as client:
                points: list[PointStruct] = []
                section_types = [
                    "cgm_range_stats",
                    "cgm_summary_stats",
                    "hyper_stats",
                    "hypo_stats",
                ]

                for section_name in section_types:
                    summary_text, section_payload = generate_section_summary(
                        patient_id,
                        section_name,
                        overall_report[section_name],
                        overview_start_time,
                        overview_end_time,
                    )
                    vector = await embed_text(summary_text)

                    points.append(
                        PointStruct(
                            id=str(uuid.uuid4()),
                            vector=vector,
                            payload={
                                "patient_id": patient_id,
                                "report_id": report_id,
                                "data_type": section_name,
                                "start_time": overview_start_time,
                                "end_time": overview_end_time,
                                "text_repr": summary_text,
                                "data": section_payload,
                            },
                        )
                    )

                # Store hyper events
                for event in overall_report["hyper_stats"]["hyper_events"]:
                    event_text = (
                        f"Patient {patient_id} hyper event: "
                        f"start {event['start_time']}, end {event['end_time']}, "
                        f"duration {event['duration']} minutes, "
                        f"peak glucose {event['peak_glucose_level']}."
                    )
                    vector = await embed_text(event_text)

                    points.append(
                        PointStruct(
                            id=str(uuid.uuid4()),
                            vector=vector,
                            payload={
                                "patient_id": patient_id,
                                "report_id": report_id,
                                "data_type": "hyper_event",
                                "text_repr": event_text,
                                "start_time": event["start_time"],
                                "end_time": event["end_time"],
                                "duration": event["duration"],
                                "peak_glucose_level": event[
                                    "peak_glucose_level"
                                ],
                            },
                        )
                    )

                # Store hypo events
                for event in overall_report["hypo_stats"]["hypo_events"]:
                    event_text = (
                        f"Patient {patient_id} hypo event: "
                        f"start {event['start_time']}, end {event['end_time']}, "
                        f"duration {event['duration']} minutes, "
                        f"lowest glucose {event['lowest_glucose_level']}."
                    )
                    vector = await embed_text(event_text)

                    points.append(
                        PointStruct(
                            id=str(uuid.uuid4()),
                            vector=vector,
                            payload={
                                "patient_id": patient_id,
                                "report_id": report_id,
                                "data_type": "hypo_event",
                                "text_repr": event_text,
                                "start_time": event["start_time"],
                                "end_time": event["end_time"],
                                "duration": event["duration"],
                                "lowest_glucose_level": event[
                                    "lowest_glucose_level"
                                ],
                            },
                        )
                    )

                # Store rapid spike stats summary
                spike_stats = overall_report["hyper_stats"].get(
                    "rapid_spike_stats", {}
                )
                if spike_stats:
                    spike_summary_text = (
                        f"Patient {patient_id} rapid spike stats from {overview_start_time.isoformat()} to {overview_end_time.isoformat()}: "
                        f"total spike duration {spike_stats.get('total_spike_duration', 0)} mins, "
                        f"{spike_stats.get('spike_events_count', 0)} events, "
                        f"average spike duration {spike_stats.get('average_spike_duration', 0):.2f} mins."
                    )
                    spike_vector = await embed_text(spike_summary_text)

                    points.append(
                        PointStruct(
                            id=str(uuid.uuid4()),
                            vector=spike_vector,
                            payload={
                                "patient_id": patient_id,
                                "report_id": report_id,
                                "data_type": "rapid_spike_stats",
                                "start_time": overall_report["start_date"],
                                "end_time": overall_report["end_date"],
                                "text_repr": spike_summary_text,
                                "data": {
                                    "total_spike_duration": spike_stats.get(
                                        "total_spike_duration", 0
                                    ),
                                    "average_spike_duration": spike_stats.get(
                                        "average_spike_duration", 0
                                    ),
                                    "spike_events_count": spike_stats.get(
                                        "spike_events_count", 0
                                    ),
                                },
                            },
                        )
                    )

                    # Store individual spike events
                    for event in spike_stats.get("spike_events", []):
                        spike_event_text = (
                            f"Patient {patient_id} rapid spike event: "
                            f"start {event['start_time']}, end {event['end_time']}, "
                            f"duration {event['duration']} mins, "
                            f"initial glucose {event['initial_glucose_level']}, "
                            f"peak glucose {event['peak_glucose_level']} at {event.get('peak_glucose_time')}."
                        )
                        spike_event_vector = await embed_text(spike_event_text)

                        points.append(
                            PointStruct(
                                id=str(uuid.uuid4()),
                                vector=spike_event_vector,
                                payload={
                                    "patient_id": patient_id,
                                    "report_id": report_id,
                                    "data_type": "rapid_spike_event",
                                    "text_repr": spike_event_text,
                                    "start_time": event["start_time"],
                                    "end_time": event["end_time"],
                                    "duration": event["duration"],
                                    "initial_glucose_level": event[
                                        "initial_glucose_level"
                                    ],
                                    "peak_glucose_level": event[
                                        "peak_glucose_level"
                                    ],
                                    "peak_glucose_time": event.get(
                                        "peak_glucose_time", "N/A"
                                    ),
                                },
                            )
                        )

                # Store rapid drop stats summary
                drop_stats = overall_report["hypo_stats"].get(
                    "rapid_drop_stats", {}
                )
                if drop_stats:
                    drop_text = (
                        f"Patient {patient_id} rapid drop stats from {overview_start_time.isoformat()} to {overview_end_time.isoformat()}:  "
                        f"total drop duration {drop_stats.get('total_drop_duration', 0)} mins, "
                        f"{drop_stats.get('drop_events_count', 0)} events, "
                        f"average drop duration {drop_stats.get('average_drop_duration', 0):.2f} mins."
                    )
                    vector = await embed_text(drop_text)
                    points.append(
                        PointStruct(
                            id=str(uuid.uuid4()),
                            vector=vector,
                            payload={
                                "patient_id": patient_id,
                                "report_id": report_id,
                                "data_type": "rapid_drop_stats_summary",
                                "start_time": overview_start_time,
                                "end_time": overview_end_time,
                                "text_repr": drop_text,
                                "data": {
                                    "total_drop_duration": drop_stats.get(
                                        "total_drop_duration", 0
                                    ),
                                    "average_drop_duration": drop_stats.get(
                                        "average_drop_duration", 0
                                    ),
                                    "drop_events_count": drop_stats.get(
                                        "drop_events_count", 0
                                    ),
                                },
                            },
                        )
                    )

                # Store each drop event
                for event in drop_stats.get("drop_events", []):
                    event_text = (
                        f"Patient {patient_id} rapid drop event: "
                        f"start {event['start_time']}, end {event['end_time']}, "
                        f"duration {event['duration']} mins, "
                        f"initial glucose {event['initial_glucose_level']}, "
                        f"lowest glucose {event['lowest_glucose_level']} "
                        f"at {event.get('lowest_glucose_time', 'N/A')}."
                    )
                    vector = await embed_text(event_text)
                    points.append(
                        PointStruct(
                            id=str(uuid.uuid4()),
                            vector=vector,
                            payload={
                                "patient_id": patient_id,
                                "report_id": report_id,
                                "data_type": "rapid_drop_event",
                                "text_repr": event_text,
                                "start_time": event["start_time"],
                                "end_time": event["end_time"],
                                "duration": event["duration"],
                                "initial_glucose_level": event[
                                    "initial_glucose_level"
                                ],
                                "lowest_glucose_level": event[
                                    "lowest_glucose_level"
                                ],
                                "lowest_glucose_time": event.get(
                                    "lowest_glucose_time"
                                ),
                            },
                        )
                    )

                # Store each time period separately
                time_period_stats = overall_report["time_period_stats"]
                for period_name, period_data in time_period_stats.items():
                    period_text = (
                        f"Patient {patient_id} {period_name} period "
                        f"(from {overview_start_time.date()} to {overview_end_time.date()}): "
                        f"average glucose {period_data.get('average_glucose', 0):.2f}, "
                        f"highest glucose {period_data.get('highest_glucose', 0)}, "
                        f"lowest glucose {period_data.get('lowest_glucose', 0)}, "
                        f"out-of-range percentage {period_data.get('out_of_range_percentage', 0):.2f}%, "
                        f"from {period_data.get('from_time')} to {period_data.get('to_time')}."
                    )
                    period_vector = await embed_text(period_text)

                    points.append(
                        PointStruct(
                            id=str(uuid.uuid4()),
                            vector=period_vector,
                            payload={
                                "patient_id": patient_id,
                                "report_id": report_id,
                                "data_type": "time_period_stats",
                                "time_period": period_name,
                                "text_repr": period_text,
                                "start_time": overview_start_time,
                                "end_time": overview_end_time,
                                "from_time": period_data.get("from_time"),
                                "to_time": period_data.get("to_time"),
                                "data": period_data,
                            },
                        )
                    )

                agp_points = overall_report["cgm_summary_stats"]["agp_points"]
                if agp_points:
                    for agp_point in agp_points:
                        point_text = (
                            f"Patient {patient_id} AGP point for {agp_point.get('hour')}: "
                            f"median {agp_point.get('median', 0)}, tenth percentile {agp_point.get('tenth_percentile', 0)}, "
                            f"ninetieth percentile {agp_point.get('ninetieth_percentile', 0)}, "
                            f"25th percentile {agp_point.get('twenty_fifth_percentile', 0)}, "
                            f"75th percentile {agp_point.get('seventy_fifth_percentile', 0)}, "
                            f"report period from {overview_start_time.isoformat()} to {overview_end_time.isoformat()}."
                        )
                        vector = await embed_text(point_text)

                        points.append(
                            PointStruct(
                                id=str(uuid.uuid4()),
                                vector=vector,
                                payload={
                                    "patient_id": patient_id,
                                    "report_id": report_id,
                                    "data_type": "agp_point",
                                    "hour": agp_point["hour"],
                                    "text_repr": point_text,
                                    "start_time": overview_start_time,
                                    "end_time": overview_end_time,
                                    "hour_time": agp_point["hour"],
                                    "data": agp_point,
                                },
                            )
                        )

                # 🚀 Upsert into Qdrant
                await client.upsert(
                    collection_name=self.collection_name,
                    points=points,
                )

            logger.info(
                f"✅ Stored report {report_id} for patient {patient_id} in Qdrant"
            )
        except Exception as e:
            logger.error(
                f"❌ Failed to upsert CGM report {report_id} for patient {patient_id}: {e}"
            )

    async def search_similar_reports(
        self,
        filter_conditions,
        query_embedding: list[float],
        limit: int = 5,
        data_types: Optional[list[str]] = None,
    ):
        async with self.qdrant_store.get_client() as client:
            if not filter_conditions and data_types:
                conditions: List[Condition] = cast(
                    List[Condition],
                    [
                        FieldCondition(
                            key="data_type", match=MatchValue(value=data_type)
                        )
                        for data_type in data_types
                    ],
                )

                filter_conditions = Filter(
                    should=conditions,
                    min_should=MinShould(conditions=conditions, min_count=1),
                )

            print("==> filter_conditions: ", filter_conditions)

            return await client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                limit=limit,
                query_filter=filter_conditions,
            )
