from datetime import datetime
import logging
from typing import Any, List, Optional
import uuid
from qdrant_client.models import PointStruct
from openai import AsyncOpenAI

from lib.core.qdrant_store import QdrantStore
from lib.services.cgm_report_service_v2.src.cgm_vector.section_configs import (
    get_stats_section_names,
)
from lib.services.cgm_report_service_v2.src.cgm_vector.section_processor import (
    CGMSectionProcessor,
)
from lib.services.cgm_report_service_v2.src.cgm_vector.section_templates import (
    CGMSectionTemplates,
)
from qdrant_client.http.models import (
    Filter,
    FieldCondition,
    MatchValue,
    Condition,
    MatchAny,
)


logger = logging.getLogger(__name__)


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

        self._patient_id = None
        self._report_id = None
        self._patient_age = None
        self._patient_gender = None

    async def upsert_report(
        self,
        patient_id: str,
        report_id: str,
        reports: List[Any],
        patient_age: int,
        patient_gender: str,
    ):
        self._patient_id = patient_id
        self._report_id = report_id
        self._patient_age = patient_age
        self._patient_gender = patient_gender

        try:
            async with self.qdrant_store.get_client() as client:
                points: list[PointStruct] = []

                for report_data in reports:
                    period_points = await self._process_report_period(
                        report_data,
                    )
                    points.extend(period_points)

                # Upsert all points
                if points:
                    await client.upsert(
                        collection_name=self.collection_name,
                        points=points,
                    )

            logger.info(
                f"✅ Stored report {self._report_id} for patient {self._patient_id} in Qdrant with {len(points)} points"
            )

        except Exception as e:
            logger.error(
                f"❌ Failed to upsert CGM report {self._report_id} "
                f"for patient {self._patient_id}: {e}"
            )
            raise

        finally:
            # Reset after use so we don’t leak values
            self._patient_id = None
            self._report_id = None
            self._patient_age = None
            self._patient_gender = None

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
        point_infos: list[dict],
    ) -> list[PointStruct]:
        texts = [info["text_repr"] for info in point_infos]

        response = await self.openai_client.embeddings.create(
            model="text-embedding-3-small", input=texts
        )

        points: list[PointStruct] = []
        for i, info in enumerate(point_infos):
            embedding = response.data[i].embedding
            payload = {
                "patient_id": self._patient_id,
                "patient_age": self._patient_age,
                "patient_gender": self._patient_gender,
                "report_id": self._report_id,
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
                    id=str(uuid.uuid4()), vector=embedding, payload=payload
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
                data_type=f"time_period_stats",
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
                data_type=f"agp_point",
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

    async def _process_report_period(
        self,
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
        ]

        for method in process_methods:
            infos = await method(report_data, start_time, end_time)
            point_infos.extend(infos)

        point_infos.extend(await self._process_events(report_data))

        return await self._batch_create_points(point_infos)

    async def search_similar_reports(
        self,
        query_embedding: list[float],
        filter_conditions: Optional[Filter] = None,
        limit: int = 500,
        data_types: Optional[List[str]] = None,
        score_threshold: Optional[float] = None,
        patient_id: Optional[str] = None,
    ):
        """
        Search for reports similar to a given embedding with optional filtering.

        Args:
            query_embedding: Vector embedding for the query.
            filter_conditions: Pre-built Qdrant filter conditions.
            limit: Max number of results to return.
            data_types: Optional list of data_type strings to filter by.
            patient_id: Optional patient ID filter.
            score_threshold: Minimum score for returned results.

        Returns:
            List of matching reports.
        """
        async with self.qdrant_store.get_client() as client:
            default_filter = self._build_filter(data_types, patient_id)
            merged_filter = self._merge_filters(
                filter_conditions, default_filter
            )

            print(f"Searching with filter: {merged_filter}, limit: {limit}")

            return await client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                limit=limit,
                query_filter=merged_filter,
                score_threshold=score_threshold,
            )

    def _build_filter(
        self,
        data_types: Optional[List[str]],
        patient_id: Optional[str],
    ) -> Optional[Filter]:
        """
        Build a Qdrant Filter from optional data_types and patient_id.
        """
        conditions: List[Condition] = []

        if data_types:
            conditions.append(self._create_data_type_condition(data_types))

        if patient_id:
            conditions.append(self._create_patient_id_condition(patient_id))

        if conditions:
            return Filter(must=conditions)

        return None

    def _merge_filters(
        self, base_filter: Optional[Filter], extra_filter: Optional[Filter]
    ) -> Optional[Filter]:
        if base_filter and extra_filter:
            return Filter(
                must=(base_filter.must or []) + (extra_filter.must or []),  # type: ignore
                should=(base_filter.should or [])
                + (extra_filter.should or []),  # type: ignore
                must_not=(base_filter.must_not or [])
                + (extra_filter.must_not or []),  # type: ignore
            )
        return base_filter or extra_filter

    @staticmethod
    def _create_data_type_condition(data_types: List[str]) -> FieldCondition:
        return FieldCondition(key="data_type", match=MatchAny(any=data_types))

    @staticmethod
    def _create_patient_id_condition(patient_id: str) -> FieldCondition:
        return FieldCondition(
            key="patient_id", match=MatchValue(value=patient_id)
        )
