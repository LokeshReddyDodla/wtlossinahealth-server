from datetime import datetime, timedelta
import hashlib
import json
import logging
from typing import Any, List, Optional
from qdrant_client.models import PointStruct
from openai import AsyncOpenAI

from lib.core.qdrant_store import QdrantStore
from lib.services.cgm_vector_service.section_configs import (
    get_stats_section_names,
)
from lib.services.cgm_vector_service.section_processor import (
    CGMSectionProcessor,
)
from lib.services.cgm_vector_service.section_templates import (
    CGMSectionTemplates,
)

from lib.utils.vector_utils import embed_text_batch_safe


logger = logging.getLogger(__name__)

CHUNK_SIZE = 200


class CGMVectorService:
    def __init__(
        self,
        qdrant_store: QdrantStore,
        collection_name: str = "patient_data",
    ):
        self.qdrant_store = qdrant_store
        self.collection_name = collection_name
        self.processor = CGMSectionProcessor()
        self.openai_client = AsyncOpenAI()

    async def upsert_report(
        self,
        patient_id: str,
        reports: List[Any],
        patient_age: int,
        patient_gender: str,
    ):
        try:
            points: list[PointStruct] = []

            for report_data in reports:
                period_points = await self._process_report_period(
                    patient_id=patient_id,
                    patient_age=patient_age,
                    patient_gender=patient_gender,
                    report_id=report_data["_id"],
                    report_data=report_data,
                )
                points.extend(period_points)

            # Upsert all points
            if points:
                await self.qdrant_store.upsert_points_chunked(
                    self.collection_name, points, CHUNK_SIZE
                )

            logger.info(
                f"✅ Stored report for patient {patient_id} in Qdrant with {len(points)} points"
            )

        except Exception as e:
            logger.error(
                f"❌ Failed to upsert CGM report "
                f"for patient {patient_id}: {e}"
            )
            raise

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

    def _create_point_info(
        self,
        data_type: str,
        text_repr: str,
        start_time: datetime,
        end_time: datetime,
        additional_payload: Optional[dict] = None,
    ) -> Any:
        return {
            "data_type": data_type,
            "text_repr": text_repr,
            "start_time": start_time,
            "end_time": end_time,
            "additional_payload": additional_payload or {},
        }

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

    async def _process_main_sections(
        self,
        report_data: dict,
        start_time: datetime,
        end_time: datetime,
    ) -> List[PointStruct]:
        """Process main statistical sections"""
        points: list[PointStruct] = []
        section_types = get_stats_section_names()

        for section_name in section_types:
            if section_name not in report_data:
                continue

            summary_text, section_payload = (
                self.processor.generate_section_summary(
                    section_name,
                    report_data[section_name],
                    start_time,
                    end_time,
                )
            )

            point = self._create_point_info(
                data_type=section_name,
                text_repr=summary_text,
                start_time=start_time,
                end_time=end_time,
                additional_payload={
                    "data": section_payload,
                },
            )
            points.append(point)

        return points

    async def _process_events(
        self,
        report_data: dict,
    ) -> List[PointStruct]:
        points: list[PointStruct] = []

        event_configs = {
            "hyper_events": ("hyper_event", "hyper_stats"),
            "hypo_events": ("hypo_event", "hypo_stats"),
            "spike_events": ("rapid_spike_event", "rapid_spike_stats"),
            "drop_events": ("rapid_drop_event", "rapid_drop_stats"),
        }

        for event_key, (
            event_data_type,
            parent_section,
        ) in event_configs.items():
            events = report_data.get(parent_section, {}).get(event_key, [])

            for event in events:
                summary_text, _ = self.processor.generate_section_summary(
                    event_data_type,
                    event,
                    event["start_time"],
                    event["end_time"],
                )

                point = self._create_point_info(
                    data_type=f"{event_data_type}",
                    text_repr=summary_text,
                    start_time=event["start_time"],
                    end_time=event["end_time"],
                    additional_payload={
                        "duration_minutes": event.get("duration_minutes"),
                        **{
                            k: v
                            for k, v in event.items()
                            if k not in ["start_time", "end_time"]
                        },
                    },
                )
                points.append(point)

        return points

    async def _process_rapid_change_stats(
        self,
        report_data: dict,
        start_time: datetime,
        end_time: datetime,
    ) -> List[PointStruct]:
        """Process rapid spike/drop statistics"""
        points: list[PointStruct] = []

        rapid_stats_configs = [
            ("rapid_spike_stats", "hyper_stats", "rapid_spike_stats"),
            ("rapid_drop_stats", "hypo_stats", "rapid_drop_stats"),
        ]

        for stats_key, parent_section, data_type in rapid_stats_configs:
            stats_data = report_data.get(parent_section, {}).get(stats_key)
            if stats_data:
                summary_text, section_payload = (
                    self.processor.generate_section_summary(
                        data_type,
                        stats_data,
                        start_time,
                        end_time,
                    )
                )

                point = self._create_point_info(
                    data_type=f"{data_type}",
                    text_repr=summary_text,
                    start_time=start_time,
                    end_time=end_time,
                    additional_payload={
                        "data": section_payload,
                    },
                )
                points.append(point)

        return points

    async def _process_time_period_stats(
        self,
        report_data: dict,
        start_time: datetime,
        end_time: datetime,
    ) -> List[PointStruct]:
        """Process time period statistics"""
        points: list[PointStruct] = []
        time_period_stats = report_data.get("time_period_stats", {})

        for period_name, period_data in time_period_stats.items():
            summary_text = CGMSectionTemplates.time_period_stats(
                period_name,
                start_time,
                end_time,
                period_data,
            )

            point = self._create_point_info(
                data_type="time_period_stats",
                text_repr=summary_text,
                start_time=start_time,
                end_time=end_time,
                additional_payload={
                    "time_period": period_name,
                    "data": period_data,
                    "from_time": period_data.get("from_time"),
                    "to_time": period_data.get("to_time"),
                },
            )
            points.append(point)

        return points

    async def _process_agp_points(
        self,
        report_data: dict,
        start_time: datetime,
        end_time: datetime,
    ) -> List[PointStruct]:
        """Process AGP points"""
        points: list[PointStruct] = []
        agp_points = report_data.get("cgm_summary_stats", {}).get(
            "agp_points", []
        )

        start_str = start_time.isoformat()
        end_str = end_time.isoformat()

        for agp_point in agp_points:
            summary_text = CGMSectionTemplates.agp_point(
                start_str, end_str, agp_point
            )

            hour_str = agp_point.get("hour")
            hour_val = None
            if hour_str:
                try:
                    dt = datetime.strptime(
                        hour_str, "%I:%M %p"
                    )  # parse 12-hr time
                    hour_val = dt.hour
                except ValueError:
                    hour_val = None

            point = self._create_point_info(
                data_type="agp_point",
                text_repr=summary_text,
                start_time=start_time,
                end_time=end_time,
                additional_payload={
                    "hour": hour_val,
                    "data": agp_point,
                },
            )
            points.append(point)

        return points

    def _parse_timestamp(self, timestamp: Any) -> Optional[datetime]:
        """Parse timestamp from various formats"""
        if isinstance(timestamp, datetime):
            return timestamp
        if isinstance(timestamp, str):
            try:
                # Try ISO format first
                return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                try:
                    # Try common formats
                    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]:
                        try:
                            return datetime.strptime(timestamp, fmt)
                        except ValueError:
                            continue
                except Exception:
                    pass
        return None

    def _bucket_30_minutes(self, dt: datetime) -> datetime:
        """Round down to the nearest 30-minute bucket"""
        # Round down minutes to 0 or 30
        minute = (dt.minute // 30) * 30
        return dt.replace(minute=minute, second=0, microsecond=0)

    async def _process_cgm_readings(
        self,
        report_data: dict,
        start_time: datetime,
        end_time: datetime,
    ) -> List[PointStruct]:
        """Process CGM readings into 30-minute buckets"""
        points: list[PointStruct] = []
        cgm_readings = report_data.get("cgm_readings", [])

        if not cgm_readings:
            return points

        # Group readings into 30-minute buckets
        buckets: dict[datetime, list[dict]] = {}

        for reading in cgm_readings:
            # Parse timestamp
            timestamp = self._parse_timestamp(
                reading.get("device_timestamp")
            )
            if not timestamp:
                continue

            # Skip readings outside report period
            if timestamp < start_time or timestamp > end_time:
                continue

            glucose_mgdl = reading.get("glucose_mgdl")
            if glucose_mgdl is None:
                continue

            # Bucket the timestamp
            bucket_start = self._bucket_30_minutes(timestamp)
            bucket_end = bucket_start + timedelta(minutes=30)

            if bucket_start not in buckets:
                buckets[bucket_start] = []

            buckets[bucket_start].append({
                "device_timestamp": timestamp,
                "glucose_mgdl": float(glucose_mgdl),
            })

        # Process each bucket
        for bucket_start in sorted(buckets.keys()):
            bucket_readings = buckets[bucket_start]
            bucket_end = bucket_start + timedelta(minutes=30)

            if not bucket_readings:
                continue

            # Compute statistics
            glucose_values = [r["glucose_mgdl"] for r in bucket_readings]
            readings_count = len(glucose_values)
            min_glucose_mgdl = min(glucose_values)
            max_glucose_mgdl = max(glucose_values)
            avg_glucose_mgdl = sum(glucose_values) / readings_count

            # Create summary data
            bucket_data = {
                "readings_count": readings_count,
                "min_glucose_mgdl": min_glucose_mgdl,
                "avg_glucose_mgdl": avg_glucose_mgdl,
                "max_glucose_mgdl": max_glucose_mgdl,
            }

            # Generate summary text using template
            summary_text = CGMSectionTemplates.cgm_semantic_window(
                bucket_start.isoformat(),
                bucket_end.isoformat(),
                bucket_data,
            )

            # Store raw readings in payload
            point = self._create_point_info(
                data_type="cgm_semantic_window",
                text_repr=summary_text,
                start_time=bucket_start,
                end_time=bucket_end,
                additional_payload={
                    **bucket_data,
                },
            )
            points.append(point)

        return points

    async def _process_report_period(
        self,
        patient_id: str,
        report_id: str,
        patient_age: int,
        patient_gender: str,
        report_data: dict,
    ) -> List[PointStruct]:
        """Process a single report period"""
        start_time = report_data["start_date"]
        end_time = report_data["end_date"]

        point_infos = []

        process_methods = [
            self._process_main_sections,
            self._process_rapid_change_stats,
            self._process_time_period_stats,
            self._process_agp_points,
            self._process_cgm_readings,
        ]

        for method in process_methods:
            infos = await method(report_data, start_time, end_time)
            point_infos.extend(infos)

        point_infos.extend(await self._process_events(report_data))

        return await self._batch_create_points(
            patient_id, report_id, patient_age, patient_gender, point_infos
        )

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

        if data_type == "agp_point":
            hour = (
                additional_payload.get("hour") if additional_payload else None
            )
            base += f"-hour_{hour}"

        elif data_type == "time_period_stats":
            period_name = (
                additional_payload.get("time_period")
                if additional_payload
                else None
            )
            base += f"-period_{period_name}"

        elif data_type == "cgm_semantic_window":
            # Use bucket start time for uniqueness
            bucket_start = start_time.isoformat()
            base += f"-bucket_{bucket_start}"

        elif data_type.endswith("_event"):
            event_hash = hashlib.md5(
                json.dumps(additional_payload, sort_keys=True).encode()
            ).hexdigest()[:8]
            base += f"-{event_hash}"

        return hashlib.md5(base.encode()).hexdigest()
