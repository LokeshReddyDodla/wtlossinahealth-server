import hashlib
import logging
from datetime import date, datetime, time
from typing import List

from pymongo import ReplaceOne

from lib.schemas.sleep_stats import SleepStats
from lib.utils.date_utils import (
    get_month_start_end,
    get_week_start_and_end_from_week_no,
)
from lib.utils.sleep.sleep_stats_processor import SleepReportType


class SleepReportService:
    def __init__(self, sleep_report_collection):
        self.sleep_report_collection = sleep_report_collection

    async def fetch_daily_reports_in_range(
        self, patient_id: str, start_date: date, end_date: date
    ):
        try:
            reports = (
                await self.sleep_report_collection.find(
                    {
                        "patient_id": patient_id,
                        "report_type": SleepReportType.DAILY,
                        "start_date": {"$gte": start_date},
                        "end_date": {"$lte": end_date},
                    },
                    {"_id": 0},
                )
                .sort("start_date", 1)
                .to_list(length=None)
            )

            return reports
        except Exception as error:
            logging.error(
                f"❌ Failed to fetch daily sleep reports for {patient_id} from {start_date} to {end_date}. Error: {error}"
            )
            return []

    async def fetch_daily_report(self, patient_id: str, date: date):
        try:
            start_date = datetime.combine(date, time.min)
            end_date = datetime.combine(date, time.max).replace(microsecond=0)

            report = await self.sleep_report_collection.find_one(
                {
                    "patient_id": patient_id,
                    "report_type": SleepReportType.DAILY,
                    "start_date": start_date,
                    "end_date": end_date,
                },
                {"_id": 0},
            )
            if not report:
                self._trigger_report_generation(
                    patient_id, start_date, end_date, SleepReportType.DAILY
                )

            return report
        except Exception as error:
            logging.error(
                f"❌ Failed to fetch daily sleep report for {patient_id} on {date}. Error: {error}"
            )
            return None

    async def fetch_weekly_report(
        self, patient_id: str, year: int, week_no: int
    ):
        try:
            start_date, end_date = get_week_start_and_end_from_week_no(
                year, week_no
            )

            report = await self.sleep_report_collection.find_one(
                {
                    "patient_id": patient_id,
                    "report_type": SleepReportType.WEEKLY,
                    "start_date": start_date,
                    "end_date": end_date,
                },
                {"_id": 0},
            )
            if not report:
                self._trigger_report_generation(
                    patient_id, start_date, end_date, SleepReportType.WEEKLY
                )

            return report
        except Exception as error:
            logging.error(
                f"❌ Failed to fetch weekly sleep report for {patient_id} (Year: {year}, Week: {week_no}). Error: {error}"
            )
            return None

    async def fetch_monthly_report(
        self, patient_id: str, year: int, month_no: int
    ):
        try:
            start_date, end_date = get_month_start_end(year, month_no)

            report = await self.sleep_report_collection.find_one(
                {
                    "patient_id": patient_id,
                    "report_type": SleepReportType.MONTHLY,
                    "start_date": start_date,
                    "end_date": end_date,
                },
                {"_id": 0},
            )
            if not report:
                self._trigger_report_generation(
                    patient_id, start_date, end_date, SleepReportType.MONTHLY
                )
            return report
        except Exception as error:
            logging.error(
                f"❌ Failed to fetch monthly sleep report for {patient_id} (Year: {year}, Month: {month_no}). Error: {error}"
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
                "lib.tasks.sleep_tasks.generate_sleep_report",
                args=[patient_id, start_date, end_date, report_type],
                task_id=f"{patient_id}_{start_date}_{end_date}_{report_type}",
            )

            print(
                f"🚀 Triggered {report_type} report generation for {patient_id} from {start_date} to {end_date}"
            )
        except Exception as error:
            logging.error(
                f"❌ Failed to trigger {report_type} sleep report generation for {patient_id}. Error: {error}"
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

    async def save_reports_bulk(self, patient_id, reports: List[SleepStats]):
        try:
            from pymongo import UpdateOne
            from datetime import datetime

            now = datetime.now()
            ops = []

            operations = []
            now = datetime.now()

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
                await self.sleep_report_collection.bulk_write(ops)
                print(
                    f"✅ Bulk saved {len(ops)} Sleep reports for {patient_id}"
                )
            else:
                print("⚠️ No Fitness reports to save.")

        except Exception as e:
            print(f"Failed to save reports in bulk: {e}")
            raise
