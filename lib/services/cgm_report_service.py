import hashlib
import logging
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional

from lib.schemas.cgm_stats import CGMStats
from lib.utils.cgm.processor import CGMReportType


class CGMReportService:
    def __init__(
        self,
        cgm_report_collection,
        meal_report_service,
        fitness_report_service,
    ):
        self.cgm_report_collection = cgm_report_collection
        self.meal_report_service = meal_report_service
        self.fitness_report_service = fitness_report_service

    async def fetch_reports(self, patient_id: str):
        try:
            reports_cursor = self.cgm_report_collection.find(
                {
                    "patient_id": patient_id,
                    "report_type": CGMReportType.CUSTOM,
                },
                {
                    "_id": 1,
                    "start_date": 1,
                    "end_date": 1,
                },
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
                {
                    "$match": {
                        "_id": report_id,
                        "patient_id": patient_id,
                        "report_type": "custom",
                    }
                },
                {
                    "$lookup": {
                        "from": "meal_reports",
                        "localField": "meal_report_id",
                        "foreignField": "_id",
                        "as": "meal_report",
                    }
                },
                {
                    "$lookup": {
                        "from": "fitness_reports",
                        "localField": "fitness_report_id",
                        "foreignField": "_id",
                        "as": "fitness_report",
                    }
                },
                {
                    "$unwind": {
                        "path": "$meal_report",
                        "preserveNullAndEmptyArrays": True,
                    }
                },
                {
                    "$unwind": {
                        "path": "$fitness_report",
                        "preserveNullAndEmptyArrays": True,
                    }
                },
                {
                    "$project": {
                        "meal_report_id": 0,
                        "fitness_report_id": 0,
                    }
                },
            ]

            custom_cursor = self.cgm_report_collection.aggregate(pipeline)
            custom_results = await custom_cursor.to_list(length=1)
            custom_report = custom_results[0] if custom_results else None

            if not custom_report:
                logging.warning(
                    f"⚠️ No custom CGM report found for {patient_id} with ID {report_id}"
                )
                return None

            overall = custom_report
            start_date = custom_report["start_date"]
            end_date = custom_report["end_date"]

            # Step 2: Fetch matching daily and weekly reports
            other_cursor = self.cgm_report_collection.aggregate(
                [
                    {
                        "$match": {
                            "patient_id": patient_id,
                            "report_type": {"$in": ["daily", "weekly"]},
                            "start_date": {"$gte": start_date},
                            "end_date": {"$lte": end_date},
                        }
                    },
                    {
                        "$lookup": {
                            "from": "meal_reports",
                            "localField": "meal_report_id",
                            "foreignField": "_id",
                            "as": "meal_report",
                        }
                    },
                    {
                        "$lookup": {
                            "from": "fitness_reports",
                            "localField": "fitness_report_id",
                            "foreignField": "_id",
                            "as": "fitness_report",
                        }
                    },
                    {
                        "$unwind": {
                            "path": "$meal_report",
                            "preserveNullAndEmptyArrays": True,
                        }
                    },
                    {
                        "$unwind": {
                            "path": "$fitness_report",
                            "preserveNullAndEmptyArrays": True,
                        }
                    },
                    {
                        "$project": {
                            "meal_report_id": 0,
                            "fitness_report_id": 0,
                        }
                    },
                ]
            )

            day_wise = []
            week_wise = []

            async for report in other_cursor:
                if report["report_type"] == "daily":
                    day_wise.append(report)
                elif report["report_type"] == "weekly":
                    week_wise.append(report)

            return {
                "overall": overall,
                "day_wise": day_wise,
                "week_wise": week_wise,
            }

        except Exception as error:
            logging.error(
                f"❌ Failed to fetch full CGM report for {patient_id} with report_id {report_id}. Error: {error}"
            )
            return None

    async def fetch_day_report(self, patient_id: str, date: date):
        try:
            start_date = datetime.combine(date, time.min)
            end_date = datetime.combine(date, time.max).replace(microsecond=0)

            cursor = self.cgm_report_collection.aggregate(
                [
                    {
                        "$match": {
                            "patient_id": patient_id,
                            "report_type": "daily",
                            "start_date": start_date,
                            "end_date": end_date,
                        }
                    },
                    {
                        "$lookup": {
                            "from": "meal_reports",
                            "localField": "meal_report_id",
                            "foreignField": "_id",
                            "as": "meal_report",
                        }
                    },
                    {
                        "$lookup": {
                            "from": "fitness_reports",
                            "localField": "fitness_report_id",
                            "foreignField": "_id",
                            "as": "fitness_report",
                        }
                    },
                    {
                        "$unwind": {
                            "path": "$meal_report",
                            "preserveNullAndEmptyArrays": True,
                        }
                    },
                    {
                        "$unwind": {
                            "path": "$fitness_report",
                            "preserveNullAndEmptyArrays": True,
                        }
                    },
                    {
                        "$project": {
                            "meal_report_id": 0,
                            "fitness_report_id": 0,
                        }
                    },
                    {"$limit": 1},
                ]
            )
            report = await cursor.to_list(length=1)
            return report[0] if report else None

        except Exception as error:
            logging.error(
                f"❌ Failed to fetch day report for {patient_id} on {date}. Error: {error}"
            )
            return None

    async def fetch_day_wise_reports(
        self, patient_id: str, start_date: datetime, end_date: datetime
    ) -> list[dict]:
        try:
            pipeline = [
                {
                    "$match": {
                        "patient_id": patient_id,
                        "report_type": "daily",
                        "start_date": {"$gte": start_date},
                        "end_date": {"$lte": end_date},
                    }
                },
                {
                    "$project": {
                        "meal_report_id": 0,
                        "fitness_report_id": 0,
                    }
                },
            ]

            cursor = self.cgm_report_collection.aggregate(pipeline)
            day_wise_reports = await cursor.to_list(length=None)

            if not day_wise_reports:
                logging.warning(
                    f"⚠️ No day_wise CGM reports found for {patient_id} ({start_date} - {end_date})"
                )

            return day_wise_reports

        except Exception as error:
            logging.error(
                f"❌ Failed to fetch day_wise CGM reports for {patient_id}. Error: {error}"
            )
            return []

    def _trigger_report_generation(
        self, patient_id: str, start_date: datetime, end_date: datetime
    ):
        try:
            from lib.dependencies.service_dependencies import (
                get_celery_task_manager,
            )

            task_manager = get_celery_task_manager()
            task_manager.trigger_task_once(
                "lib.tasks.cgm_tasks.generate_and_store_cgm_report",
                args=[patient_id, start_date, end_date],
                task_id=f"{patient_id}_{start_date}_{end_date}",
                queue="cgm_reports",
            )

            print(
                f"🚀 Triggered cgm report generation for {patient_id} from {start_date} to {end_date}"
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

    async def save_report(self, patient_id: str, report: CGMStats):
        try:
            report_id = self._generate_report_id(
                patient_id,
                report.report_type,
                report.start_date,
                report.end_date,
            )
            now = datetime.now()
            existing_report = await self.cgm_report_collection.find_one(
                {"_id": report_id}
            )

            report_dict = report.model_dump(exclude_none=True)
            report_dict.update(
                {
                    "_id": report_id,
                    "patient_id": patient_id,
                    "created_at": (
                        existing_report.get("created_at", now)
                        if existing_report
                        else now
                    ),
                    "updated_at": now,
                }
            )

            # Upsert the report (insert if new, update if exists)
            await self.cgm_report_collection.replace_one(
                {"_id": report_id}, report_dict, upsert=True
            )

            print(
                f"✅ Saved/Updated cgm report for {patient_id} from {report.start_date} to {report.end_date}"
            )

            return report_id

        except Exception as error:
            print(
                f"❌ Failed to save cgm report for {patient_id} from {report.start_date} to {report.end_date}. Error: {error}"
            )
            raise

    async def save_reports_bulk(
        self, patient_id: str, reports: List[CGMStats]
    ):
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

            # Save fitness report separately for 'custom' report_type
            if report.fitness_report:
                fitness_report_id = self._generate_report_id(
                    patient_id,
                    report.fitness_report.report_type,
                    report.start_date,
                    report.end_date,
                )
                existing_fitness_report = (
                    await self.fitness_report_service.fetch_report_by_id(
                        fitness_report_id
                    )
                )

                if not existing_fitness_report:
                    fitness_report_id = (
                        await self.fitness_report_service.save_report(
                            patient_id, report.fitness_report
                        )
                    )
                report_dict["fitness_report_id"] = fitness_report_id
                report_dict.pop("fitness_report", None)

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
            await self.cgm_report_collection.bulk_write(ops)
            print(f"✅ Bulk saved {len(ops)} CGM reports for {patient_id}")
            return report_id
        else:
            print("⚠️ No CGM reports to save.")
