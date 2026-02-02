import hashlib
import logging
from datetime import date, datetime, time
from typing import List, Optional

from pymongo import ReplaceOne

from lib.schemas.fitness_stats import FitnessStats
from lib.utils.date_utils import (
    get_month_start_end,
    get_week_start_and_end_from_week_no,
)
from lib.services.reports import FitnessReportType


class FitnessReportService:
    def __init__(self, fitness_report_collection, patient_summary_service=None):
        self.fitness_report_collection = fitness_report_collection
        self.patient_summary_service = patient_summary_service

    async def _mark_summaries_stale(
        self, patient_id: str, start_date: datetime, end_date: datetime
    ) -> None:
        if not self.patient_summary_service:
            return

        try:
            from lib.services.patient_summary.enum import StaleReason

            await self.patient_summary_service.mark_summaries_as_stale(
                patient_id=patient_id,
                start_date=start_date,
                end_date=end_date,
                stale_reason=StaleReason.DATA_UPDATED,
            )
        except Exception as e:
            # Don't fail the save operation if marking stale fails
            logging.warning(
                f"Failed to mark summaries as stale for {patient_id}: {e}"
            )

    async def fetch_report_by_id(self, report_id: str) -> Optional[dict]:
        try:
            return await self.fitness_report_collection.find_one(
                {"_id": report_id}
            )
        except Exception as error:
            logging.error(
                f"❌ Failed to fetch report by ID {report_id}: {error}"
            )
            return None

    async def fetch_daily_reports_in_range(
        self,
        patient_id: str,
        start_date: date,
        end_date: date,
        include_id: bool = False,
    ):
        try:
            projection = {}
            if not include_id:
                projection["_id"] = 0

            reports = (
                await self.fitness_report_collection.find(
                    {
                        "patient_id": patient_id,
                        "report_type": FitnessReportType.DAILY,
                        "start_date": {"$gte": start_date},
                        "end_date": {"$lte": end_date},
                    },
                    projection,
                )
                .sort("start_date", 1)
                .to_list(length=None)
            )

            return reports
        except Exception as error:
            logging.error(
                f"❌ Failed to fetch daily reports for {patient_id} from {start_date} to {end_date}. Error: {error}"
            )
            return []

    async def fetch_daily_report(
        self, patient_id: str, date: date, regenerate: bool = False
    ):
        try:
            start_date = datetime.combine(date, time.min)
            end_date = datetime.combine(date, time.max).replace(microsecond=0)

            if regenerate:
                self._trigger_report_generation(
                    patient_id, start_date, end_date, FitnessReportType.DAILY
                )
                return None

            report = await self.fitness_report_collection.find_one(
                {
                    "patient_id": patient_id,
                    "report_type": FitnessReportType.DAILY,
                    "start_date": start_date,
                    "end_date": end_date,
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
                f"❌ Failed to fetch daily report for {patient_id} on {date}. Error: {error}"
            )
            return None

    async def fetch_weekly_report(
        self, patient_id: str, year: int, week_no: int
    ):
        try:
            start_date, end_date = get_week_start_and_end_from_week_no(
                year, week_no
            )

            report = await self.fitness_report_collection.find_one(
                {
                    "patient_id": patient_id,
                    "report_type": FitnessReportType.WEEKLY,
                    "start_date": start_date,
                    "end_date": end_date,
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
                f"❌ Failed to fetch weekly report for {patient_id} (Week {week_no}, {year}). Error: {error}"
            )
            return None

    async def fetch_monthly_report(
        self, patient_id: str, year: int, month_no: int
    ):
        try:
            start_date, end_date = get_month_start_end(year, month_no)

            report = await self.fitness_report_collection.find_one(
                {
                    "patient_id": patient_id,
                    "report_type": FitnessReportType.MONTHLY,
                    "start_date": start_date,
                    "end_date": end_date,
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
                f"❌ Failed to fetch monthly report for {patient_id} (Month {month_no}, {year}). Error: {error}"
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
            from lib.dependencies.service_dependencies import (
                get_celery_task_manager,
            )

            task_manager = get_celery_task_manager()
            task_manager.trigger_task_once(
                "lib.tasks.fitness_tasks.generate_and_store_fitness_report",
                args=[patient_id, start_date, end_date, report_type],
                task_id=f"{patient_id}_{start_date}_{end_date}_{report_type}",
                queue="default",
            )

            print(
                f"🚀 Triggered {report_type} report generation for {patient_id} from {start_date} to {end_date}"
            )
        except Exception as error:
            logging.error(
                f"❌ Failed to trigger report generation for {patient_id} from {start_date} to {end_date}. Error: {error}"
            )

    def _generate_report_id(
        self,
        patient_id: str,
        report_type: str,
        start: datetime,
        end: datetime,
    ) -> str:
        key = f"{patient_id}_{report_type}_{start.date()}_{end.date()}"
        return hashlib.sha256(key.encode()).hexdigest()

    async def save_report(self, patient_id: str, report: FitnessStats):
        try:
            now = datetime.now()
            report_id = self._generate_report_id(
                patient_id,
                report.report_type,
                report.start_date,
                report.end_date,
            )

            existing = await self.fitness_report_collection.find_one(
                {"_id": report_id}
            )

            report_dict = report.model_dump(exclude_none=True)
            report_dict.update(
                {
                    "_id": report_id,
                    "patient_id": patient_id,
                    "created_at": (
                        existing.get("created_at", now) if existing else now
                    ),
                    "updated_at": now,
                }
            )

            await self.fitness_report_collection.replace_one(
                {"_id": report_id},
                report_dict,
                upsert=True,
            )

            print(
                f"✅ Saved/Updated fitness report for {patient_id} ({report.report_type}) from {report.start_date} to {report.end_date}"
            )

            # Mark affected summaries as stale
            await self._mark_summaries_stale(
                patient_id=patient_id,
                start_date=report.start_date,
                end_date=report.end_date,
            )

            return report_id

        except Exception as e:
            print(f"❌ Failed to save report: {e}")
            raise

    async def save_reports_bulk(
        self, patient_id: str, reports: List[FitnessStats]
    ):
        try:
            from pymongo import UpdateOne
            from datetime import datetime

            now = datetime.now()
            ops = []

            for report in reports:
                report_dict = report.model_dump(exclude_none=True)
                report_id = self._generate_report_id(
                    patient_id,
                    report.report_type,
                    report.start_date,
                    report.end_date,
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
                    UpdateOne(
                        {"_id": report_id}, {"$set": report_dict}, upsert=True
                    )
                )

            if ops:
                await self.fitness_report_collection.bulk_write(ops)
                print(
                    f"✅ Bulk saved {len(ops)} Fitness reports for {patient_id}"
                )

                # Mark affected summaries as stale
                for report in reports:
                    await self._mark_summaries_stale(
                        patient_id=patient_id,
                        start_date=report.start_date,
                        end_date=report.end_date,
                    )
            else:
                print("⚠️ No Fitness reports to save.")
        except Exception as e:
            print(f"Failed to save reports in bulk: {e}")
            raise
