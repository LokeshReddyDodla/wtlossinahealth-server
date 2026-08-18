"""Sleep vector service — one `sleep` point per daily report."""

import logging
from typing import Any

from lib.core.qdrant_store import QdrantStore

from ..base import BaseVectorService
from ..utils.constants import DEFAULT_CHUNK_SIZE
from .text_builder import build_sleep_text

logger = logging.getLogger(__name__)

_DATA_TYPE = "sleep"


class SleepVectorService(BaseVectorService):
    """Vectorizes wearable-staged daily sleep reports for AI retrieval."""

    def __init__(self, qdrant_store: QdrantStore, collection_name: str = "patient_data"):
        super().__init__(qdrant_store, collection_name)

    async def upsert_report(
        self,
        patient_id: str,
        reports: list[dict[str, Any]],
        patient_age: int,
        patient_gender: str,
    ) -> None:
        try:
            points: list[Any] = []
            for report in reports:
                if self._is_empty_report(report):
                    continue

                start_time, end_time = self._extract_dates_from_report(
                    report, report.get("_id")
                )
                text = build_sleep_text(
                    start_time.isoformat(), end_time.isoformat(), report
                )
                report_points = await self._batch_create_points(
                    patient_id=patient_id,
                    patient_age=patient_age,
                    patient_gender=patient_gender,
                    point_infos=[
                        {
                            "data_type": _DATA_TYPE,
                            "text_repr": text,
                            "start_time": start_time,
                            "end_time": end_time,
                        }
                    ],
                    report_id=report["_id"],
                )
                points.extend(report_points)

            if points:
                await self.upsert_points_batch(points, DEFAULT_CHUNK_SIZE)

            logger.info(
                f"✅ Stored sleep vectors for patient {patient_id}: {len(points)} points"
            )
        except Exception as e:
            logger.error(f"❌ Failed to upsert sleep report for patient {patient_id}: {e}")
            raise

    def _is_empty_report(self, report: dict[str, Any]) -> bool:
        return not ((report.get("duration") or {}).get("total_duration"))
