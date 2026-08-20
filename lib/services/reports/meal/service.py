from lib.services.reports.base import report_id as base_report_id
import logging
from datetime import date, datetime

from lib.services.patient_summary.enum import StaleReason
from lib.utils.patient_summary_stale import mark_summary_stale_and_enqueue


class MealReportService:
    def __init__(self, meal_report_collection, patient_summary_service=None):
        self.meal_report_collection = meal_report_collection
        self.patient_summary_service = patient_summary_service

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

            # regenerate forces a rebuild but still serves the current doc.
            if regenerate:
                await self.trigger_daily_report_generation(patient_id, report_date)

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
                if not regenerate:
                    await self.trigger_daily_report_generation(patient_id, report_date)
                return None

            if "meals" in report and isinstance(report["meals"], list):
                report["meals"].sort(key=lambda m: m.get("time", ""))

            return report
        except Exception as error:
            logging.error(
                f"Failed to fetch daily meal report for {patient_id} on {report_date}: {error}"
            )
            return None

    async def trigger_daily_report_generation(
        self,
        patient_id: str,
        report_date: date,
    ):
        try:
            from lib.workers.tasks.meal.enqueue import enqueue_daily_meal_report_async

            await enqueue_daily_meal_report_async(patient_id, report_date)
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

            report_id = base_report_id(patient_id, report_type, date_iso)
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

            # Mark summary as stale and enqueue regeneration job
            await mark_summary_stale_and_enqueue(
                patient_id=patient_id,
                target_date=report_date_obj,
                stale_reason=StaleReason.DATA_UPDATED,
            )

        except Exception as error:
            logging.error(f"Failed to save daily report for {patient_id}: {error}")
            raise
