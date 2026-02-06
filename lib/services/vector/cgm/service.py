"""CGM vector service for processing and storing CGM data."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from lib.core.qdrant_store import QdrantStore

from ..base import BaseVectorService
from ..utils.constants import DEFAULT_CHUNK_SIZE
from .configs import get_stats_section_names
from .processor import CGMSectionProcessor
from .templates import CGMSectionTemplates

logger = logging.getLogger(__name__)


class CGMVectorService(BaseVectorService):
    """Service for vectorizing CGM report data."""

    def __init__(
        self,
        qdrant_store: QdrantStore,
        collection_name: str = "patient_data",
    ):
        """
        Initialize CGM vector service.

        Args:
            qdrant_store: Qdrant store instance
            collection_name: Collection name for vector storage
        """
        super().__init__(qdrant_store, collection_name)
        self.processor = CGMSectionProcessor()

    async def upsert_report(
        self,
        patient_id: str,
        reports: List[Any],
        patient_age: int,
        patient_gender: str,
    ) -> None:
        """
        Upsert CGM reports to vector store.

        Args:
            patient_id: Patient identifier
            reports: List of CGM report data
            patient_age: Patient age
            patient_gender: Patient gender

        Raises:
            VectorServiceError: If upsert fails
        """
        try:
            points: List[Any] = []

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
                await self.upsert_points_batch(points, DEFAULT_CHUNK_SIZE)

            logger.info(
                f"✅ Stored CGM report for patient {patient_id} in Qdrant "
                f"with {len(points)} points"
            )

        except Exception as e:
            logger.error(
                f"❌ Failed to upsert CGM report for patient {patient_id}: {e}"
            )
            raise

    def _create_point_info(
        self,
        data_type: str,
        text_repr: str,
        start_time: datetime,
        end_time: datetime,
        additional_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create point info dictionary.

        Args:
            data_type: Data type identifier
            text_repr: Text representation
            start_time: Start datetime
            end_time: End datetime
            additional_payload: Optional additional payload

        Returns:
            Point info dictionary
        """
        return {
            "data_type": data_type,
            "text_repr": text_repr,
            "start_time": start_time,
            "end_time": end_time,
            "additional_payload": additional_payload or {},
        }

    async def _process_main_sections(
        self,
        report_data: Dict[str, Any],
        start_time: datetime,
        end_time: datetime,
    ) -> List[Dict[str, Any]]:
        """Process main statistical sections."""
        point_infos: List[Dict[str, Any]] = []
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

            point_info = self._create_point_info(
                data_type=section_name,
                text_repr=summary_text,
                start_time=start_time,
                end_time=end_time,
                additional_payload={"data": section_payload},
            )
            point_infos.append(point_info)

        return point_infos

    async def _process_events(
        self,
        report_data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Process event sections."""
        point_infos: List[Dict[str, Any]] = []

        event_configs = {
            "hyper_events": ("hyper_event", "hyper_stats"),
            "hypo_events": ("hypo_event", "hypo_stats"),
            "spike_events": ("rapid_spike_event", "rapid_spike_stats"),
            "drop_events": ("rapid_drop_event", "rapid_drop_stats"),
        }

        for event_key, (event_data_type, parent_section) in event_configs.items():
            events = report_data.get(parent_section, {}).get(event_key, [])

            for event in events:
                summary_text, _ = self.processor.generate_section_summary(
                    event_data_type,
                    event,
                    event["start_time"],
                    event["end_time"],
                )

                point_info = self._create_point_info(
                    data_type=event_data_type,
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
                point_infos.append(point_info)

        return point_infos

    async def _process_rapid_change_stats(
        self,
        report_data: Dict[str, Any],
        start_time: datetime,
        end_time: datetime,
    ) -> List[Dict[str, Any]]:
        """Process rapid spike/drop statistics."""
        point_infos: List[Dict[str, Any]] = []

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

                point_info = self._create_point_info(
                    data_type=data_type,
                    text_repr=summary_text,
                    start_time=start_time,
                    end_time=end_time,
                    additional_payload={"data": section_payload},
                )
                point_infos.append(point_info)

        return point_infos

    async def _process_time_period_stats(
        self,
        report_data: Dict[str, Any],
        start_time: datetime,
        end_time: datetime,
    ) -> List[Dict[str, Any]]:
        """Process time period statistics."""
        point_infos: List[Dict[str, Any]] = []
        time_period_stats = report_data.get("time_period_stats", {})

        for period_name, period_data in time_period_stats.items():
            summary_text = CGMSectionTemplates.time_period_stats(
                period_name,
                start_time,
                end_time,
                period_data,
            )

            point_info = self._create_point_info(
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
            point_infos.append(point_info)

        return point_infos

    async def _process_agp_points(
        self,
        report_data: Dict[str, Any],
        start_time: datetime,
        end_time: datetime,
    ) -> List[Dict[str, Any]]:
        """Process AGP points."""
        point_infos: List[Dict[str, Any]] = []
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
                    dt = datetime.strptime(hour_str, "%I:%M %p")
                    hour_val = dt.hour
                except ValueError:
                    hour_val = None

            point_info = self._create_point_info(
                data_type="agp_point",
                text_repr=summary_text,
                start_time=start_time,
                end_time=end_time,
                additional_payload={
                    "hour": hour_val,
                    "data": agp_point,
                },
            )
            point_infos.append(point_info)

        return point_infos

    def _parse_timestamp(self, timestamp: Any) -> Optional[datetime]:
        """Parse timestamp from various formats."""
        if isinstance(timestamp, datetime):
            return timestamp
        if isinstance(timestamp, str):
            try:
                # Try ISO format first
                return datetime.fromisoformat(
                    timestamp.replace("Z", "+00:00")
                )
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
        """Round down to the nearest 30-minute bucket."""
        minute = (dt.minute // 30) * 30
        return dt.replace(minute=minute, second=0, microsecond=0)

    async def _process_cgm_readings(
        self,
        report_data: Dict[str, Any],
        start_time: datetime,
        end_time: datetime,
    ) -> List[Dict[str, Any]]:
        """Process CGM readings into 30-minute buckets."""
        point_infos: List[Dict[str, Any]] = []
        cgm_readings = report_data.get("cgm_readings", [])

        if not cgm_readings:
            return point_infos

        # Group readings into 30-minute buckets
        buckets: Dict[datetime, List[Dict[str, Any]]] = {}

        for reading in cgm_readings:
            # Parse timestamp
            timestamp = self._parse_timestamp(reading.get("device_timestamp"))
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
            point_info = self._create_point_info(
                data_type="cgm_semantic_window",
                text_repr=summary_text,
                start_time=bucket_start,
                end_time=bucket_end,
                additional_payload=bucket_data,
            )
            point_infos.append(point_info)

        return point_infos

    async def _process_report_period(
        self,
        patient_id: str,
        report_id: str,
        patient_age: int,
        patient_gender: str,
        report_data: Dict[str, Any],
    ) -> List[Any]:
        """Process a single report period."""
        start_time = report_data["start_date"]
        end_time = report_data["end_date"]

        point_infos: List[Dict[str, Any]] = []

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

        # Use base class method to create points
        return await self._batch_create_points(
            patient_id=patient_id,
            patient_age=patient_age,
            patient_gender=patient_gender,
            point_infos=point_infos,
            report_id=report_id,
        )
