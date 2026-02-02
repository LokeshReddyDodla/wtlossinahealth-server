import hashlib
import logging
from datetime import date, datetime


class MealReportService:
    def __init__(self, meal_report_collection, patient_summary_service=None):
        self.meal_report_collection = meal_report_collection
        self.patient_summary_service = patient_summary_service

    async def _mark_summaries_stale(self, patient_id: str, report_date: date) -> None:
        if not self.patient_summary_service:
            return

        try:
            from lib.services.patient_summary.enum import StaleReason

            await self.patient_summary_service.mark_summaries_as_stale(
                patient_id=patient_id,
                target_date=report_date,
                stale_reason=StaleReason.DATA_UPDATED,
            )
        except Exception as e:
            logging.warning(f"Failed to mark summaries as stale for {patient_id}: {e}")

    async def fetch_report_by_id(self, report_id: str):
        try:
            report = await self.meal_report_collection.find_one({"_id": report_id})
            return report
        except Exception as error:
            logging.error(f"Failed to fetch meal report by ID {report_id}: {error}")
            return None

    async def fetch_daily_reports_in_range(
        self, patient_id: str, start_date: date, end_date: date
    ):
        try:
            start_iso = start_date.isoformat()
            end_iso = end_date.isoformat()

            reports = (
                await self.meal_report_collection.find(
                    {
                        "patient_id": patient_id,
                        "report_type": "daily",
                        "$or": [
                            {"date": {"$gte": start_iso, "$lte": end_iso}},
                            {
                                "metadata.date_range.start": {
                                    "$gte": start_iso,
                                    "$lte": end_iso,
                                }
                            },
                        ],
                    },
                    {"_id": 0},
                )
                .sort("date", 1)
                .to_list(length=None)
            )

            return reports
        except Exception as error:
            logging.error(
                f"Failed to fetch daily meal reports for {patient_id} from {start_date} to {end_date}: {error}"
            )
            return []

    async def fetch_daily_report(
        self, patient_id: str, report_date: date, regenerate: bool = False
    ):
        try:
            date_iso = report_date.isoformat()

            if regenerate:
                self.trigger_daily_report_generation(patient_id, report_date)
                return None

            report = await self.meal_report_collection.find_one(
                {
                    "patient_id": patient_id,
                    "$or": [
                        {"date": date_iso},
                        {"metadata.date_range.start": {"$regex": f"^{date_iso}"}},
                    ],
                },
                {"_id": 0},
            )
            if not report:
                self.trigger_daily_report_generation(patient_id, report_date)

            return report
        except Exception as error:
            logging.error(
                f"Failed to fetch daily meal report for {patient_id} on {report_date}: {error}"
            )
            return None

    def trigger_daily_report_generation(
        self,
        patient_id: str,
        report_date: date,
    ):
        try:
            from lib.dependencies.service_dependencies import get_celery_task_manager

            task_manager = get_celery_task_manager()
            task_manager.trigger_task_once(
                "lib.tasks.meal_tasks.generate_daily_meal_report",
                args=[patient_id, report_date],
                task_id=f"{patient_id}_{report_date}",
                queue="default",
            )
            logging.info(
                f"Triggered daily report generation for {patient_id} on {report_date}"
            )
        except Exception as error:
            logging.error(
                f"Failed to trigger daily report generation for {patient_id} on {report_date}: {error}"
            )

    async def save_report(self, patient_id: str, report: dict):
        try:
            report_type = report.get("report_type", "daily")
            date_value = report.get("date") or report.get("metadata", {}).get(
                "date_range", {}
            ).get("start", "")

            if isinstance(date_value, date):
                date_iso = date_value.isoformat()
            elif isinstance(date_value, str):
                date_iso = date_value.split("T")[0] if "T" in date_value else date_value
            else:
                date_iso = str(date_value)

            unique_key = f"{patient_id}_{report_type}_{date_iso}"
            report_id = hashlib.sha256(unique_key.encode()).hexdigest()
            now = datetime.now()

            existing_report = await self.meal_report_collection.find_one(
                {"_id": report_id}
            )
            report["created_at"] = (
                existing_report.get("created_at", now) if existing_report else now
            )
            report["updated_at"] = now
            report["_id"] = report_id

            if "date" in report and not isinstance(report["date"], str):
                report["date"] = (
                    report["date"].isoformat()
                    if hasattr(report["date"], "isoformat")
                    else str(report["date"])
                )

            await self.meal_report_collection.replace_one(
                {"_id": report_id}, report, upsert=True
            )

            report_date_obj = (
                datetime.fromisoformat(date_iso).date()
                if isinstance(date_iso, str) and "T" not in date_iso
                else datetime.fromisoformat(date_iso.split("T")[0]).date()
            )
            logging.info(
                f"Saved/Updated daily report for {patient_id} on {report_date_obj}"
            )

            await self._mark_summaries_stale(
                patient_id=patient_id, report_date=report_date_obj
            )

        except Exception as error:
            logging.error(f"Failed to save daily report for {patient_id}: {error}")
            raise
