import hashlib
import os
from datetime import date, datetime, time

from dotenv import load_dotenv
from pymongo import MongoClient, ReplaceOne

load_dotenv()
MONGO_URL = os.getenv("MONGO_URL")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")


class MealReportService:
    def __init__(self):
        self.mongo_client = MongoClient(str(MONGO_URL))
        self.db = self.mongo_client[str(MONGO_DB_NAME)]
        self.meal_report_collection = self.db["meal_reports"]

    def fetch_daily_reports_in_range(
        self, patient_id: str, from_date: date, to_date: date
    ):
        reports = list(
            self.meal_report_collection.find(
                {
                    "patient_id": patient_id,
                    "report_type": "daily",
                    "date": {"$gte": from_date.isoformat()},
                    "date": {"$lte": to_date.isoformat()},
                },
                {"_id": 0},
            )
        )

        return reports

    def fetch_daily_report(self, patient_id: str, report_date: date):
        report = self.meal_report_collection.find_one(
            {"patient_id": patient_id, "date": report_date.isoformat()},
            {"_id": 0},
        )
        if not report:
            self.trigger_daily_report_generation(patient_id, report_date)

        return report

    def trigger_daily_report_generation(
        self,
        patient_id: str,
        report_date: date,
    ):
        from lib.core.celery_app import celery

        celery.send_task(
            "lib.tasks.meal_tasks.generate_daily_meal_report",
            args=[str(patient_id), report_date],
        )
        print(
            f"🚀 Triggered daily report generation for {patient_id} on {report_date}"
        )

    def save_report(self, patient_id: str, report: dict):
        try:
            unique_key = (
                f"{patient_id}_{report['report_type']}_{report['date']}"
            )
            report_id = hashlib.sha256(unique_key.encode()).hexdigest()

            report["_id"] = report_id
            report["date"] = report["date"].isoformat()

            # Upsert the report (insert if new, update if exists)
            self.meal_report_collection.replace_one(
                {"_id": report_id}, report, upsert=True
            )

            print(
                f"✅ Saved/Updated daily report for {patient_id} on {report['date']}"
            )

        except Exception as error:
            print(
                f"❌ Failed to save daily report for {patient_id} on {report['date']}. Error: {error}"
            )
