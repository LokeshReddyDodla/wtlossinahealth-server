import hashlib
import logging
from datetime import date, datetime, time, timedelta
from typing import List, Optional

from lib.schemas.fitness_stats import FitnessStats
from lib.services.patient_summary.enum import StaleReason
from lib.utils.date_utils import (
    get_month_start_end,
    get_week_start_and_end_from_week_no,
)
from lib.utils.datetime_utils import parse_datetime
from lib.utils.patient_summary_stale import mark_summary_stale_and_enqueue
from .processor import FitnessReportType

class FitnessReportService:
    def __init__(self, fitness_report_collection, patient_summary_service=None):
        self.fitness_report_collection = fitness_report_collection
        self.patient_summary_service = patient_summary_service

    async def _mark_summaries_stale_for_range(
        self, patient_id: str, start_date: datetime, end_date: datetime
    ) -> None:
        """Mark summaries as stale and enqueue regeneration for each date in range."""
        try:
            # Iterate through each day in the range
            current_date = start_date.date()
            end_date_obj = end_date.date()
            
            while current_date <= end_date_obj:
                await mark_summary_stale_and_enqueue(
                    patient_id=patient_id,
                    target_date=current_date,
                    stale_reason=StaleReason.DATA_UPDATED,
                )
                current_date += timedelta(days=1)
        except Exception as e:
            logging.warning(f"Failed to mark summaries as stale for {patient_id}: {e}")

    async def fetch_report_by_id(self, report_id: str) -> Optional[dict]:
        try:
            return await self.fitness_report_collection.find_one({"_id": report_id})
        except Exception as error:
            logging.error(f"❌ Failed to fetch report by ID {report_id}: {error}")
            return None

    async def fetch_daily_reports_in_range(
        self,
        patient_id: str,
        start_date: date,
        end_date: date,
        include_id: bool = False,
    ):
        try:
            projection = {} if include_id else {"_id": 0}
            start_iso = datetime.combine(start_date, time.min).isoformat()
            end_iso = (
                datetime.combine(end_date, time.max).replace(microsecond=0).isoformat()
            )

            reports = (
                await self.fitness_report_collection.find(
                    {
                        "patient_id": patient_id,
                        "metadata.report_type": FitnessReportType.DAILY,
                        "metadata.date_range.start": {"$gte": start_iso},
                        "metadata.date_range.end": {"$lte": end_iso},
                    },
                    projection,
                )
                .sort("metadata.date_range.start", 1)
                .to_list(length=None)
            )

            return reports
        except Exception as error:
            logging.error(
                f"Failed to fetch daily reports for {patient_id} from {start_date} to {end_date}: {error}"
            )
            return []

    async def fetch_daily_report(
        self, patient_id: str, date: date, regenerate: bool = False
    ):
        try:
            start_date = datetime.combine(date, time.min)
            end_date = datetime.combine(date, time.max).replace(microsecond=0)
            start_iso = start_date.isoformat()
            end_iso = end_date.isoformat()

            if regenerate:
                self._trigger_report_generation(
                    patient_id, start_date, end_date, FitnessReportType.DAILY
                )
                return None

            report = await self.fitness_report_collection.find_one(
                {
                    "patient_id": patient_id,
                    "metadata.report_type": FitnessReportType.DAILY,
                    "metadata.date_range.start": start_iso,
                    "metadata.date_range.end": end_iso,
                },
                {"_id": 0},
            )
            if not report:
                self._trigger_report_generation(
                    patient_id, start_date, end_date, FitnessReportType.DAILY
                )
                return None

            return report
        except Exception as error:
            logging.error(
                f"Failed to fetch daily report for {patient_id} on {date}: {error}"
            )
            return None

    async def fetch_weekly_report(self, patient_id: str, year: int, week_no: int):
        try:
            start_date, end_date = get_week_start_and_end_from_week_no(year, week_no)
            start_iso = start_date.isoformat()
            end_iso = end_date.isoformat()

            report = await self.fitness_report_collection.find_one(
                {
                    "patient_id": patient_id,
                    "metadata.report_type": FitnessReportType.WEEKLY,
                    "metadata.date_range.start": start_iso,
                    "metadata.date_range.end": end_iso,
                },
                {"_id": 0},
            )
            if not report:
                self._trigger_report_generation(
                    patient_id, start_date, end_date, FitnessReportType.WEEKLY
                )

            return report
        except Exception as error:
            logging.error(
                f"Failed to fetch weekly report for {patient_id} (Week {week_no}, {year}): {error}"
            )
            return None

    async def fetch_monthly_report(self, patient_id: str, year: int, month_no: int):
        try:
            start_date, end_date = get_month_start_end(year, month_no)
            start_iso = start_date.isoformat()
            end_iso = end_date.isoformat()

            report = await self.fitness_report_collection.find_one(
                {
                    "patient_id": patient_id,
                    "metadata.report_type": FitnessReportType.MONTHLY,
                    "metadata.date_range.start": start_iso,
                    "metadata.date_range.end": end_iso,
                },
                {"_id": 0},
            )
            if not report:
                self._trigger_report_generation(
                    patient_id, start_date, end_date, FitnessReportType.MONTHLY
                )
            return report
        except Exception as error:
            logging.error(
                f"Failed to fetch monthly report for {patient_id} (Month {month_no}, {year}): {error}"
            )
            return None

    def _trigger_report_generation(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        report_type: str,
    ):
        try:
            from lib.workers.tasks.fitness.enqueue import (
                enqueue_process_fitness_upload_sync,
            )

            enqueue_process_fitness_upload_sync(
                patient_id, start_date, end_date
            )

            logging.info(
                f"Triggered fitness report generation for {patient_id} from {start_date} to {end_date}"
            )
        except Exception as error:
            logging.error(
                f"Failed to trigger report generation for {patient_id} from {start_date} to {end_date}: {error}"
            )

    def _generate_report_id(
        self,
        patient_id: str,
        report_type: str,
        start_iso: str,
        end_iso: str,
    ) -> str:
        key = f"{patient_id}_{report_type}_{start_iso}_{end_iso}"
        return hashlib.sha256(key.encode()).hexdigest()

    async def save_report(self, patient_id: str, report: FitnessStats):
        try:
            metadata = report.metadata
            now = datetime.now()
            report_id = self._generate_report_id(
                patient_id,
                metadata.report_type,
                metadata.date_range.start,
                metadata.date_range.end,
            )

            existing = await self.fitness_report_collection.find_one({"_id": report_id})

            report_dict = report.model_dump(exclude_none=True)
            report_dict.update(
                {
                    "_id": report_id,
                    "patient_id": patient_id,
                    "created_at": existing.get("created_at", now) if existing else now,
                    "updated_at": now,
                }
            )

            await self.fitness_report_collection.replace_one(
                {"_id": report_id}, report_dict, upsert=True
            )

            start_dt = parse_datetime(metadata.date_range.start)
            end_dt = parse_datetime(metadata.date_range.end)
            logging.info(
                f"Saved/Updated fitness report for {patient_id} ({metadata.report_type}) from {start_dt} to {end_dt}"
            )

            if start_dt and end_dt:
                await self._mark_summaries_stale_for_range(
                    patient_id=patient_id, start_date=start_dt, end_date=end_dt
                )
            else:
                logging.warning(
                    f"Could not parse datetime range for fitness report: {metadata.date_range.start} - {metadata.date_range.end}"
                )

            return report_id

        except Exception as e:
            logging.error(f"Failed to save fitness report: {e}")
            raise

    async def save_reports_bulk(self, patient_id: str, reports: List[FitnessStats]):
        try:
            from pymongo import UpdateOne

            if not reports:
                logging.warning("No Fitness reports to save")
                return

            now = datetime.now()
            ops = []

            for report in reports:
                metadata = report.metadata
                report_dict = report.model_dump(exclude_none=True)
                report_id = self._generate_report_id(
                    patient_id,
                    metadata.report_type,
                    metadata.date_range.start,
                    metadata.date_range.end,
                )

                report_dict.update(
                    {
                        "_id": report_id,
                        "patient_id": patient_id,
                        "updated_at": now,
                        "created_at": report_dict.get("created_at", now),
                    }
                )

                ops.append(
                    UpdateOne({"_id": report_id}, {"$set": report_dict}, upsert=True)
                )

            await self.fitness_report_collection.bulk_write(ops)
            logging.info(f"Bulk saved {len(ops)} Fitness reports for {patient_id}")

            for report in reports:
                metadata = report.metadata
                start_dt = parse_datetime(metadata.date_range.start)
                end_dt = parse_datetime(metadata.date_range.end)
                if start_dt and end_dt:
                    await self._mark_summaries_stale_for_range(
                        patient_id=patient_id, start_date=start_dt, end_date=end_dt
                    )
                else:
                    logging.warning(
                        f"Could not parse datetime range for fitness report: {metadata.date_range.start} - {metadata.date_range.end}"
                    )

        except Exception as e:
            logging.error(f"Failed to save reports in bulk: {e}")
            raise
