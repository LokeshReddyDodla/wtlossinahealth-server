from datetime import datetime
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from lib.core.qdrant_store import QdrantStore
from lib.services.fitness_vector_service.section_configs import STATS_CONFIGS
from lib.services.fitness_vector_service.section_processor import (
    FitnessSectionProcessor,
)
from qdrant_client.models import PointStruct

from lib.utils.vector_utils import embed_text_batch_safe


logger = logging.getLogger(__name__)

CHUNK_SIZE = 200


class FitnessVectorService:

    def __init__(
        self, qdrant_store: QdrantStore, collection_name: str = "patient_data"
    ):
        self.qdrant_store = qdrant_store
        self.collection_name = collection_name
        self.processor = FitnessSectionProcessor()

    async def upsert_report(
        self,
        patient_id: str,
        reports: List[Any],
        patient_age: int,
        patient_gender: str,
    ):
        try:
            points = []
            for report in reports:
                period_points = await self._process_report_period(
                    patient_id=patient_id,
                    report_id=report["_id"],
                    patient_age=patient_age,
                    patient_gender=patient_gender,
                    report_data=report,
                )
                points.extend(period_points)

            if points:
                await self.qdrant_store.upsert_points_chunked(
                    self.collection_name, points, CHUNK_SIZE
                )

            logger.info(
                f"✅ Stored report for patient {patient_id} in Qdrant with {len(points)} points"
            )
        except Exception as e:
            logger.error(
                f"❌ Failed to upsert Fitness report "
                f"for patient {patient_id}: {e}"
            )
            raise

    async def _process_report_period(
        self,
        patient_id: str,
        report_id: str,
        patient_age: int,
        patient_gender: str,
        report_data: Dict[str, Any],
    ):
        start_time = report_data["start_date"]
        end_time = report_data["end_date"]

        point_infos = []

        process_methods = [
            self._process_main_sections,
            self._process_events,
        ]

        for method in process_methods:
            infos = await method(report_data, start_time, end_time)
            point_infos.extend(infos)

        return await self._batch_create_points(
            patient_id=patient_id,
            report_id=report_id,
            patient_age=patient_age,
            patient_gender=patient_gender,
            point_infos=point_infos,
        )

    async def _process_main_sections(
        self,
        report_data: dict,
        start_time: datetime,
        end_time: datetime,
    ):
        results = []

        for name, config in STATS_CONFIGS.items():
            if name == "fitness_overview":
                section_data = {
                    "steps": report_data["steps"],
                    "active_duration": report_data["active_duration"],
                    "active_energy": report_data["active_energy"],
                    "average_active_session_duration": report_data[
                        "average_active_session_duration"
                    ],
                    "peak_hour": report_data["peak_activity_time"]["hour"],
                    "peak_steps": report_data["peak_activity_time"][
                        "max_steps"
                    ],
                }

            elif name == "fitness_activity_distribution":
                dist = report_data["activity_distribution"]
                section_data = {
                    "morning_steps": dist["Morning"]["steps"],
                    "morning_duration": dist["Morning"]["active_duration"],
                    "afternoon_steps": dist["Afternoon"]["steps"],
                    "afternoon_duration": dist["Afternoon"]["active_duration"],
                    "evening_steps": dist["Evening"]["steps"],
                    "evening_duration": dist["Evening"]["active_duration"],
                }

            else:
                continue

            text, payload = self.processor.generate_section_summary(
                name, section_data, start_time, end_time
            )

            results.append(
                {
                    "data_type": name,
                    "text_repr": text,
                    "start_time": start_time,
                    "end_time": end_time,
                    "additional_payload": payload,
                }
            )

        return results

    async def _process_events(self, report_data, *_):
        results = []
        events = report_data.get("inactive_periods", [])

        for evt in events:
            data = {
                "start_time": evt["start_time"],
                "end_time": evt["end_time"],
                "inactive_duration": evt["inactive_duration"],
            }

            text, payload = self.processor.generate_section_summary(
                "fitness_inactive_periods",
                data,
                evt["start_time"],
                evt["end_time"],
            )

            results.append(
                {
                    "data_type": "fitness_inactive_periods",
                    "text_repr": text,
                    "start_time": evt["start_time"],
                    "end_time": evt["end_time"],
                    "additional_payload": payload,
                }
            )

        return results

    def _bucket_time(self, hour: int) -> str:
        if 6 <= hour < 12:
            return "morning"
        elif 12 <= hour < 18:
            return "afternoon"
        elif 18 <= hour < 24:
            return "evening"
        else:
            return "night"

    def _time_buckets_for_range(
        self, start_time: datetime, end_time: datetime
    ) -> list[str]:
        buckets = set()

        # If start and end are the same day
        if start_time.date() == end_time.date():
            for hour in range(start_time.hour, end_time.hour + 1):
                buckets.add(self._bucket_time(hour))
        else:
            # If range spans multiple days → treat as "all_day"
            buckets = {"all_day"}

        return sorted(buckets)

    async def _batch_create_points(
        self,
        patient_id: str,
        report_id: str,
        patient_age: int,
        patient_gender: str,
        point_infos: list[dict],
    ) -> list[PointStruct]:
        texts = [info["text_repr"] for info in point_infos]

        embeddings = await embed_text_batch_safe(texts)

        points: list[PointStruct] = []
        for i, info in enumerate(point_infos):
            embedding = embeddings[i]

            payload = {
                "patient_id": patient_id,
                "patient_age": patient_age,
                "patient_gender": patient_gender,
                "report_id": report_id,
                "data_type": info["data_type"],
                "text_repr": info["text_repr"],
                "start_time": int(info["start_time"].timestamp() * 1000),
                "end_time": int(info["end_time"].timestamp() * 1000),
                "date": info["start_time"].date().isoformat(),
                "day_of_week": info["start_time"].weekday(),
                "is_weekend": info["start_time"].weekday() >= 5,
                "week_number": info["start_time"].isocalendar()[1],
                "month": info["start_time"].month,
                "time_of_day_bucket": self._time_buckets_for_range(
                    info["start_time"], info["end_time"]
                ),
            }

            if "additional_payload" in info and info["additional_payload"]:
                payload.update(info["additional_payload"])

            points.append(
                PointStruct(
                    id=self._generate_point_id(
                        patient_id,
                        report_id,
                        info["data_type"],
                        info["start_time"],
                        info["end_time"],
                        info.get("additional_payload"),
                    ),
                    vector=embedding,
                    payload=payload,
                )
            )

        return points

    def _generate_point_id(
        self,
        patient_id: str,
        report_id: str,
        data_type: str,
        start_time: datetime,
        end_time: datetime,
        additional_payload: Optional[dict] = None,
    ) -> str:
        base = f"{patient_id}-{report_id}-{data_type}-{start_time.isoformat()}-{end_time.isoformat()}"

        if data_type == "hourly_stats":
            hour = (
                additional_payload.get("hour") if additional_payload else None
            )
            base += f"-hour_{hour}"

        return hashlib.md5(base.encode()).hexdigest()
