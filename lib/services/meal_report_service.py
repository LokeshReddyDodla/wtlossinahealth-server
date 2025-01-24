import hashlib
from datetime import date


class MealReportService:
    def __init__(self, meal_report_collection):
        self.meal_report_collection = meal_report_collection

    async def fetch_daily_reports_in_range(
        self, patient_id: str, start_date: date, end_date: date
    ):
        reports = (
            await self.meal_report_collection.find(
                {
                    "patient_id": patient_id,
                    "report_type": "daily",
                    "date": {"$gte": start_date.isoformat()},
                    "date": {"$lte": end_date.isoformat()},
                },
                {"_id": 0},
            )
            .sort("date", 1)
            .to_list(length=None)
        )

        return reports

    async def fetch_daily_report(self, patient_id: str, report_date: date):
        report = await self.meal_report_collection.find_one(
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
        from lib.dependencies.service_dependencies import \
            get_celery_task_manager

        task_manager = get_celery_task_manager()
        task_manager.trigger_task_once(
            "lib.tasks.meal_tasks.generate_daily_meal_report",
            args=[patient_id, report_date],
            task_id=f"{patient_id}_{report_date}",
        )
        print(
            f"🚀 Triggered daily report generation for {patient_id} on {report_date}"
        )

    async def save_report(self, patient_id: str, report: dict):
        try:
            unique_key = (
                f"{patient_id}_{report['report_type']}_{report['date']}"
            )
            report_id = hashlib.sha256(unique_key.encode()).hexdigest()

            report["_id"] = report_id
            report["date"] = report["date"].isoformat()

            # Upsert the report (insert if new, update if exists)
            await self.meal_report_collection.replace_one(
                {"_id": report_id}, report, upsert=True
            )

            print(
                f"✅ Saved/Updated daily report for {patient_id} on {report['date']}"
            )

        except Exception as error:
            print(
                f"❌ Failed to save daily report for {patient_id} on {report['date']}. Error: {error}"
            )
