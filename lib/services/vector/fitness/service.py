"""Fitness vector service for processing and storing fitness data."""

import logging
from datetime import datetime
from typing import Any, Dict, List

from lib.core.qdrant_store import QdrantStore

from ..base import BaseVectorService
from ..utils.constants import DEFAULT_CHUNK_SIZE
from .configs import STATS_CONFIGS
from .processor import FitnessSectionProcessor

logger = logging.getLogger(__name__)


class FitnessVectorService(BaseVectorService):
    """Service for vectorizing Fitness report data."""

    def __init__(
        self, qdrant_store: QdrantStore, collection_name: str = "patient_data"
    ):
        """
        Initialize Fitness vector service.

        Args:
            qdrant_store: Qdrant store instance
            collection_name: Collection name for vector storage
        """
        super().__init__(qdrant_store, collection_name)
        self.processor = FitnessSectionProcessor()

    async def upsert_report(
        self,
        patient_id: str,
        reports: List[Any],
        patient_age: int,
        patient_gender: str,
    ) -> None:
        """
        Upsert Fitness reports to vector store.

        Args:
            patient_id: Patient identifier
            reports: List of Fitness report data
            patient_age: Patient age
            patient_gender: Patient gender

        Raises:
            VectorServiceError: If upsert fails
        """
        try:
            points: List[Any] = []
            for report in reports:
                if self._is_empty_report(report):
                    continue

                period_points = await self._process_report_period(
                    patient_id=patient_id,
                    report_id=report["_id"],
                    patient_age=patient_age,
                    patient_gender=patient_gender,
                    report_data=report,
                )
                points.extend(period_points)

            if points:
                await self.upsert_points_batch(points, DEFAULT_CHUNK_SIZE)

            logger.info(
                f"✅ Stored Fitness report for patient {patient_id} in Qdrant "
                f"with {len(points)} points"
            )
        except Exception as e:
            logger.error(
                f"❌ Failed to upsert Fitness report for patient {patient_id}: {e}"
            )
            raise

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
            self._process_events,
        ]

        for method in process_methods:
            infos = await method(report_data, start_time, end_time)
            point_infos.extend(infos)

        return await self._batch_create_points(
            patient_id=patient_id,
            patient_age=patient_age,
            patient_gender=patient_gender,
            point_infos=point_infos,
            report_id=report_id,
        )

    async def _process_main_sections(
        self,
        report_data: Dict[str, Any],
        start_time: datetime,
        end_time: datetime,
    ) -> List[Dict[str, Any]]:
        """Process main statistical sections."""
        results: List[Dict[str, Any]] = []

        for name, config in STATS_CONFIGS.items():
            if name == "fitness_overview":
                section_data = {
                    "steps": report_data.get("steps", 0),
                    "active_duration": report_data.get("active_duration", 0),
                    "active_energy": report_data.get("active_energy", 0.0),
                    "average_active_session_duration": report_data.get(
                        "average_active_session_duration", 0.0
                    ),
                    "peak_hour": report_data.get("peak_activity_time", {}).get(
                        "hour"
                    ),
                    "peak_steps": report_data.get(
                        "peak_activity_time", {}
                    ).get("max_steps", 0),
                    "peak_active_energy": report_data.get(
                        "peak_activity_time", {}
                    ).get("max_active_energy", 0.0),
                }

            elif name == "fitness_activity_distribution":
                dist = report_data.get("activity_distribution", {})
                section_data = {}
                for period in ["Morning", "Afternoon", "Evening", "Night"]:
                    period_data = dist.get(period, {})
                    section_data[f"{period.lower()}_steps"] = period_data.get(
                        "steps", 0
                    )
                    section_data[f"{period.lower()}_duration"] = (
                        period_data.get("active_duration", 0)
                    )
                    section_data[f"{period.lower()}_energy"] = period_data.get(
                        "active_energy", 0.0
                    )

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

    async def _process_events(
        self, report_data: Dict[str, Any], *_
    ) -> List[Dict[str, Any]]:
        """Process event sections."""
        results: List[Dict[str, Any]] = []
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

    def _is_empty_report(self, report: Dict[str, Any]) -> bool:
        """Check if report is empty."""
        return (
            report.get("steps", 0) <= 0
            and report.get("active_duration", 0) <= 0
            and report.get("active_energy", 0) <= 0
            and not report.get("inactive_periods")
        )
