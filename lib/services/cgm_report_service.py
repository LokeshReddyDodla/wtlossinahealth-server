import hashlib
import logging
from datetime import date, datetime, time
from typing import Any, Dict


class CGMReportService:
    def __init__(self, cgm_report_collection, meal_report_service):
        self.cgm_report_collection = cgm_report_collection
        self.meal_report_service = meal_report_service

    async def fetch_reports(self, patient_id: str):
        try:
            reports_cursor = self.cgm_report_collection.find(
                {"patient_id": patient_id},
                {"_id": 1, "start_date": 1, "end_date": 1},
            ).sort("start_date", 1)

            reports = await reports_cursor.to_list(length=None)

            for report in reports:
                report["report_id"] = report.pop("_id")

            return reports

        except Exception as error:
            logging.error(
                f"❌ Failed to fetch reports for {patient_id}. Error: {error}"
            )
            return []

    async def fetch_report(self, patient_id: str, report_id: str):
        try:
            pipeline = [
                {"$match": {"patient_id": patient_id, "_id": report_id}},
                # Lookup meal reports for each "day_wise" entry
                {
                    "$unwind": {
                        "path": "$day_wise",
                        "preserveNullAndEmptyArrays": True,
                    }
                },
                {
                    "$lookup": {
                        "from": "meal_reports",
                        "localField": "day_wise.meal_report_id",
                        "foreignField": "_id",
                        "as": "day_wise.meal_report",
                    }
                },
                {
                    "$unwind": {
                        "path": "$day_wise.meal_report",
                        "preserveNullAndEmptyArrays": True,
                    }
                },
                {"$unset": "overall.meal_report_id"},
                {"$unset": "day_wise.meal_report_id"},
                {"$unset": "week_wise.meal_report_id"},
                {
                    "$group": {
                        "_id": "$_id",
                        "patient_id": {"$first": "$patient_id"},
                        "start_date": {"$first": "$start_date"},
                        "end_date": {"$first": "$end_date"},
                        "updated_at": {"$first": "$updated_at"},
                        "overall": {"$first": "$overall"},
                        "day_wise": {"$push": "$day_wise"},
                        "week_wise": {"$first": "$week_wise"},
                    }
                },
                {"$project": {"_id": 0}},
            ]

            cursor = self.cgm_report_collection.aggregate(pipeline)
            report = await cursor.to_list(length=1)

            if report:
                return report[0]
            else:
                logging.warning(
                    f"⚠️ No CGM report found for {patient_id} with report_id {report_id}."
                )
                return None

        except Exception as error:
            logging.error(
                f"❌ Failed to fetch CGM report for {patient_id} with report_id {report_id}. Error: {error}"
            )
            return None

    async def fetch_day_report(self, patient_id: str, date: date):
        try:
            start_date = datetime.combine(date, time.min)
            end_date = datetime.combine(date, time.max)

            report = await self.cgm_report_collection.find_one(
                {
                    "patient_id": patient_id,
                    "start_date": {"$lte": start_date},
                    "end_date": {"$gte": end_date},
                }
            )

            if not report:
                return None

            target_date_str = date.isoformat()
            day_report = next(
                (
                    day
                    for day in report.get("day_wise", [])
                    if day["start_date"].split("T")[0] == target_date_str
                ),
                None,
            )

            if not day_report:
                return None

            # If there's a meal report ID, fetch the full meal report
            if day_report.get("meal_report_id"):
                meal_report = await self.meal_report_service.fetch_report(
                    day_report["meal_report_id"]
                )
                day_report["meal_report"] = meal_report
                del day_report["meal_report_id"]

            return day_report

        except Exception as error:
            logging.error(
                f"❌ Failed to fetch day report for {patient_id} on {date}. Error: {error}"
            )
            return None

    def _trigger_report_generation(
        self, patient_id: str, start_date: datetime, end_date: datetime
    ):
        try:
            from lib.dependencies.service_dependencies import \
                get_celery_task_manager

            task_manager = get_celery_task_manager()
            task_manager.trigger_task_once(
                "lib.tasks.cgm_tasks.generate_cgm_report",
                args=[patient_id, start_date, end_date],
                task_id=f"{patient_id}_{start_date}_{end_date}",
            )

            print(
                f"🚀 Triggered cgm report generation for {patient_id} from {start_date} to {end_date}"
            )
        except Exception as error:
            logging.error(
                f"❌ Failed to trigger report generation for {patient_id} from {start_date} to {end_date}. Error: {error}"
            )

    async def save_report(self, patient_id: str, report: Dict[str, Any]):
        try:
            unique_key = f"{patient_id}_{report['start_date']}_{report['end_date']}"
            report_id = hashlib.sha256(unique_key.encode()).hexdigest()
            now = datetime.now()

            existing_report = await self.cgm_report_collection.find_one(
                {"_id": report_id}
            )
            report["created_at"] = (
                existing_report.get("created_at", now) if existing_report else now
            )
            report["updated_at"] = now

            report["_id"] = report_id

            # Upsert the report (insert if new, update if exists)
            await self.cgm_report_collection.replace_one(
                {"_id": report_id}, report, upsert=True
            )

            print(
                f"✅ Saved/Updated cgm report for {patient_id} from {report['start_date']} to {report['end_date']}"
            )

        except Exception as error:
            print(
                f"❌ Failed to save cgm report for {patient_id} from {report['start_date']} to {report['end_date']}. Error: {error}"
            )
            raise
