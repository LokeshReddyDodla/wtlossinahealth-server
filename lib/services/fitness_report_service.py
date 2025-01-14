import hashlib
import os
from datetime import date, datetime, time

from dotenv import load_dotenv
from pymongo import MongoClient, ReplaceOne

from lib.core.types import FitnessReportTypeLiteral
from lib.utils.date_utils import (get_month_start_end,
                                  get_week_start_and_end_from_week_no)

load_dotenv()
MONGO_URL = os.getenv("MONGO_URL")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")


class FitnessReportService:
    def __init__(self):
        self.mongo_client = MongoClient(str(MONGO_URL))
        self.db = self.mongo_client[str(MONGO_DB_NAME)]
        self.fitness_report_collection = self.db["fitness_reports"]

    def fetch_daily_reports_in_range(
        self, patient_id: str, from_date: date, to_date: date
    ):
        reports = list(
            self.fitness_report_collection.find(
                {
                    "patient_id": patient_id,
                    "report_type": "daily",
                    "from_date": {"$gte": from_date},
                    "to_date": {"$lte": to_date},
                },
                {"_id": 0},
            )
        )

        return reports

    def fetch_daily_report(self, patient_id: str, date: date):
        from_date = datetime.combine(date, time.min)
        to_date = datetime.combine(date, time.max).replace(microsecond=0)

        report = self.fitness_report_collection.find_one(
            {
                "patient_id": patient_id,
                "report_type": "daily",
                "from_date": from_date,
                "to_date": to_date,
            },
            {"_id": 0},
        )
        if not report:
            self._trigger_report_generation(
                patient_id, from_date, to_date, "daily"
            )

        return report

    def fetch_weekly_report(self, patient_id: str, year: int, week_no: int):
        start_date, end_date = get_week_start_and_end_from_week_no(
            year, week_no
        )

        report = self.fitness_report_collection.find_one(
            {
                "patient_id": patient_id,
                "report_type": "weekly",
                "from_date": start_date,
                "to_date": end_date,
            },
            {"_id": 0},
        )
        if not report:
            self._trigger_report_generation(
                patient_id, start_date, end_date, "weekly"
            )

        return report

    def fetch_monthly_report(self, patient_id: str, year: int, month_no: int):
        start_date, end_date = get_month_start_end(year, month_no)

        report = self.fitness_report_collection.find_one(
            {
                "patient_id": patient_id,
                "report_type": "monthly",
                "from_date": start_date,
                "to_date": end_date,
            },
            {"_id": 0},
        )
        if not report:
            self._trigger_report_generation(
                patient_id, start_date, end_date, "monthly"
            )
        return report

    def _trigger_report_generation(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        report_type: FitnessReportTypeLiteral,
    ):
        from lib.core.celery_app import celery

        celery.send_task(
            "lib.tasks.fitness_tasks.generate_fitness_report",
            args=[str(patient_id), start_date, end_date, report_type],
        )
        print(
            f"🚀 Triggered {report_type} report generation for {patient_id} from {start_date} to {end_date}"
        )

    def save_reports_bulk(self, reports: list):
        try:
            operations = []

            for report in reports:
                unique_string = f"{report['patient_id']}_{report['report_type']}_{report['from_date']}_{report['to_date']}"
                report_id = hashlib.sha256(unique_string.encode()).hexdigest()

                report["_id"] = report_id

                operations.append(
                    ReplaceOne({"_id": report_id}, report, upsert=True)
                )

            # Perform bulk upsert
            self.fitness_report_collection.bulk_write(
                operations, ordered=False
            )
            print(f"Saved/Updated {len(reports)} reports successfully")
        except Exception as e:
            print(f"Failed to save reports in bulk: {e}")
