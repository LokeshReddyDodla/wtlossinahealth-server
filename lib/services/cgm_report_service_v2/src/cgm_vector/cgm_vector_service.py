from datetime import datetime
import logging
from typing import Any, List, Optional
import uuid
from qdrant_client.models import PointStruct

from lib.core.qdrant_store import QdrantStore
from lib.services.cgm_report_service_v2.src.cgm_vector.section_configs import (
    ReportPeriodType,
    get_stats_section_names,
)
from lib.services.cgm_report_service_v2.src.cgm_vector.section_processor import (
    CGMSectionProcessor,
)
from lib.services.cgm_report_service_v2.src.cgm_vector.section_templates import (
    CGMSectionTemplates,
)
from lib.utils.vector_utils import embed_text


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

    async def upsert_report(
        self,
        patient_id: str,
        report: Any,
    ):
        try:
            report_id = report["overall"]["_id"]

            async with self.qdrant_store.get_client() as client:
                points: list[PointStruct] = []

                # Process all report periods
                period_types = [ptype.value for ptype in ReportPeriodType]

                for period_type in period_types:
                    if period_type == "overall":
                        period_points = await self._process_report_period(
                            patient_id,
                            report_id,
                            report[period_type],
                            period_type,
                        )
                        points.extend(period_points)
                    else:
                        for period_data in report[period_type]:
                            period_points = await self._process_report_period(
                                patient_id,
                                report_id,
                                period_data,
                                period_type,
                            )
                            points.extend(period_points)

                # Upsert all points
                if points:
                    await client.upsert(
                        collection_name=self.collection_name,
                        points=points,
                    )

            logger.info(
                f"✅ Stored report {report_id} for patient {patient_id} in Qdrant with {len(points)} points"
            )

        except Exception as e:
            logger.error(
                f"❌ Failed to upsert CGM report {report.get('overall', {}).get('_id', 'unknown')} "
                f"for patient {patient_id}: {e}"
            )
            raise

    async def _create_point(
        self,
        patient_id: str,
        report_id: str,
        data_type: str,
        text_repr: str,
        start_time: datetime,
        end_time: datetime,
        additional_payload: Optional[dict] = None,
    ) -> PointStruct:
        vector = await embed_text(text_repr)
        payload = {
            "patient_id": patient_id,
            "report_id": report_id,
            "data_type": data_type,
            "start_time": start_time,
            "end_time": end_time,
            "text_repr": text_repr,
        }

        if additional_payload:
            payload.update(additional_payload)

        return PointStruct(
            id=str(uuid.uuid4()), vector=vector, payload=payload
        )

    async def _process_main_sections(
        self,
        patient_id: str,
        report_id: str,
        report_data: dict,
        start_time: datetime,
        end_time: datetime,
        period_type: str = "overall",
    ) -> List[PointStruct]:
        """Process main statistical sections"""
        points: list[PointStruct] = []
        section_types = get_stats_section_names()

        for section_name in section_types:
            if section_name not in report_data:
                continue

            summary_text, section_payload = (
                self.processor.generate_section_summary(
                    patient_id,
                    section_name,
                    report_data[section_name],
                    start_time,
                    end_time,
                )
            )

            point = await self._create_point(
                patient_id=patient_id,
                report_id=report_id,
                data_type=f"{period_type}_{section_name}",
                text_repr=summary_text,
                start_time=start_time,
                end_time=end_time,
                additional_payload={
                    "data": section_payload,
                    "period_type": period_type,
                },
            )
            points.append(point)

        return points

    async def _process_events(
        self,
        patient_id: str,
        report_id: str,
        report_data: dict,
        period_type: str,
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
                    patient_id,
                    event_data_type,
                    event,
                    event["start_time"],
                    event["end_time"],
                )

                point = await self._create_point(
                    patient_id=patient_id,
                    report_id=report_id,
                    data_type=f"{period_type}_{event_data_type}",
                    text_repr=summary_text,
                    start_time=event["start_time"],
                    end_time=event["end_time"],
                    additional_payload={
                        "duration": event.get("duration"),
                        "period_type": period_type,
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
        patient_id: str,
        report_id: str,
        report_data: dict,
        start_time: datetime,
        end_time: datetime,
        period_type: str = "overall",
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
                        patient_id, data_type, stats_data, start_time, end_time
                    )
                )

                point = await self._create_point(
                    patient_id=patient_id,
                    report_id=report_id,
                    data_type=f"{period_type}_{data_type}",
                    text_repr=summary_text,
                    start_time=start_time,
                    end_time=end_time,
                    additional_payload={
                        "data": section_payload,
                        "period_type": period_type,
                    },
                )
                points.append(point)

        return points

    async def _process_time_period_stats(
        self,
        patient_id: str,
        report_id: str,
        report_data: dict,
        start_time: datetime,
        end_time: datetime,
        period_type: str = "overall",
    ) -> List[PointStruct]:
        """Process time period statistics"""
        points: list[PointStruct] = []
        time_period_stats = report_data.get("time_period_stats", {})

        for period_name, period_data in time_period_stats.items():
            summary_text = CGMSectionTemplates.time_period_stats(
                patient_id, period_name, start_time, end_time, period_data
            )

            point = await self._create_point(
                patient_id=patient_id,
                report_id=report_id,
                data_type=f"{period_type}_time_period_stats",
                text_repr=summary_text,
                start_time=start_time,
                end_time=end_time,
                additional_payload={
                    "time_period": period_name,
                    "data": period_data,
                    "period_type": period_type,
                    "from_time": period_data.get("from_time"),
                    "to_time": period_data.get("to_time"),
                },
            )
            points.append(point)

        return points

    async def _process_agp_points(
        self,
        patient_id: str,
        report_id: str,
        report_data: dict,
        start_time: datetime,
        end_time: datetime,
        period_type: str = "overall",
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
                patient_id, start_str, end_str, agp_point
            )

            point = await self._create_point(
                patient_id=patient_id,
                report_id=report_id,
                data_type=f"{period_type}_agp_point",
                text_repr=summary_text,
                start_time=start_time,
                end_time=end_time,
                additional_payload={
                    "hour": agp_point.get("hour"),
                    "data": agp_point,
                    "period_type": period_type,
                },
            )
            points.append(point)

        return points

    async def _process_report_period(
        self,
        patient_id: str,
        report_id: str,
        period_data: dict,
        period_type: str,
    ) -> List[PointStruct]:
        """Process a single report period"""
        start_time = period_data["start_date"]
        end_time = period_data["end_date"]

        points: list[PointStruct] = []

        process_methods = [
            self._process_main_sections,
            self._process_rapid_change_stats,
            self._process_time_period_stats,
            self._process_agp_points,
        ]

        for method in process_methods:
            points.extend(
                await method(
                    patient_id,
                    report_id,
                    period_data,
                    start_time,
                    end_time,
                    period_type,
                )
            )

        points.extend(
            await self._process_events(
                patient_id, report_id, period_data, period_type
            )
        )

        return points
