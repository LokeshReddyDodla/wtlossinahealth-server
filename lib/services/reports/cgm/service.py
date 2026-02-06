import hashlib
import logging
from datetime import date, datetime, time
from typing import Dict, List

from lib.schemas.cgm_stats import CGMStats
from .processor import CGMReportType


class CGMReportService:
    def __init__(
        self,
        cgm_report_collection,
        meal_report_service,
        fitness_report_service,
        patient_summary_service=None,
    ):
        self.cgm_report_collection = cgm_report_collection
        self.meal_report_service = meal_report_service
        self.fitness_report_service = fitness_report_service
        self.patient_summary_service = patient_summary_service

    def _extract_datetime_from_iso(self, iso_string: str) -> datetime:
        """Extract datetime from ISO string, handling timezone."""
        return datetime.fromisoformat(iso_string.replace("Z", "+00:00"))

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
            logging.warning(f"Failed to mark summaries as stale for {patient_id}: {e}")

    async def fetch_reports(self, patient_id: str):
        try:
            reports_cursor = self.cgm_report_collection.find(
                {
                    "patient_id": patient_id,
                    "metadata.report_type": CGMReportType.CUSTOM,
                },
                {
                    "_id": 1,
                    "metadata.date_range": 1,
                },
            ).sort("metadata.date_range.start", 1)

            reports = await reports_cursor.to_list(length=None)

            for report in reports:
                report["report_id"] = report.pop("_id")

            return reports

        except Exception as error:
            logging.error(f"Failed to fetch reports for {patient_id}: {error}")
            return []

    async def fetch_reports_batch(
        self, patient_ids: List[str]
    ) -> Dict[str, List[Dict]]:
        try:
            if not patient_ids:
                return {}

            reports_cursor = self.cgm_report_collection.find(
                {
                    "patient_id": {"$in": patient_ids},
                    "metadata.report_type": CGMReportType.CUSTOM,
                },
                {
                    "_id": 1,
                    "patient_id": 1,
                    "metadata.date_range": 1,
                },
            ).sort([("patient_id", 1), ("metadata.date_range.start", 1)])

            reports = await reports_cursor.to_list(length=None)

            reports_by_patient: Dict[str, List[Dict]] = {pid: [] for pid in patient_ids}
            for report in reports:
                patient_id = report["patient_id"]
                report["report_id"] = report.pop("_id")
                reports_by_patient[patient_id].append(report)

            return reports_by_patient

        except Exception as error:
            logging.error(
                f"Failed to fetch reports batch for {len(patient_ids)} patients: {error}"
            )
            return {patient_id: [] for patient_id in patient_ids}

    async def fetch_report(self, patient_id: str, report_id: str):
        try:
            pipeline = [
                {
                    "$match": {
                        "_id": report_id,
                        "patient_id": patient_id,
                        "metadata.report_type": "custom",
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

            custom_results = await self.cgm_report_collection.aggregate(
                pipeline
            ).to_list(length=1)
            custom_report = custom_results[0] if custom_results else None

            if not custom_report:
                logging.warning(
                    f"No custom CGM report found for {patient_id} with ID {report_id}"
                )
                return None

            other_cursor = self.cgm_report_collection.aggregate(
                [
                    {
                        "$match": {
                            "patient_id": patient_id,
                            "metadata.report_type": {"$in": ["daily", "weekly"]},
                            "metadata.date_range.start": {
                                "$gte": custom_report["metadata"]["date_range"]["start"]
                            },
                            "metadata.date_range.end": {
                                "$lte": custom_report["metadata"]["date_range"]["end"]
                            },
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
                report_type = report.get("metadata", {}).get("report_type", "")
                if report_type == "daily":
                    day_wise.append(report)
                elif report_type == "weekly":
                    week_wise.append(report)

            return {
                "overall": custom_report,
                "day_wise": day_wise,
                "week_wise": week_wise,
            }

        except Exception as error:
            logging.error(
                f"Failed to fetch full CGM report for {patient_id} with report_id {report_id}: {error}"
            )
            return None

    async def fetch_day_report(self, patient_id: str, date: date):
        try:
            start_date = datetime.combine(date, time.min)
            end_date = datetime.combine(date, time.max).replace(microsecond=0)
            start_iso = start_date.isoformat()
            end_iso = end_date.isoformat()

            cursor = self.cgm_report_collection.aggregate(
                [
                    {
                        "$match": {
                            "patient_id": patient_id,
                            "metadata.report_type": "daily",
                            "metadata.date_range.start": start_iso,
                            "metadata.date_range.end": end_iso,
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
                f"Failed to fetch day report for {patient_id} on {date}: {error}"
            )
            return None

    async def fetch_day_wise_reports(
        self, patient_id: str, start_date: datetime, end_date: datetime
    ) -> list[dict]:
        try:
            start_iso = start_date.isoformat()
            end_iso = end_date.isoformat()

            pipeline = [
                {
                    "$match": {
                        "patient_id": patient_id,
                        "metadata.report_type": "daily",
                        "metadata.date_range.start": {"$gte": start_iso},
                        "metadata.date_range.end": {"$lte": end_iso},
                    }
                },
                {
                    "$project": {
                        "meal_report_id": 0,
                        "fitness_report_id": 0,
                    }
                },
            ]

            day_wise_reports = await self.cgm_report_collection.aggregate(
                pipeline
            ).to_list(length=None)

            if not day_wise_reports:
                logging.warning(
                    f"No day_wise CGM reports found for {patient_id} ({start_date} - {end_date})"
                )

            return day_wise_reports

        except Exception as error:
            logging.error(
                f"Failed to fetch day_wise CGM reports for {patient_id}: {error}"
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
        start_iso: str,
        end_iso: str,
    ) -> str:
        key = f"{patient_id}_{report_type}_{start_iso}_{end_iso}"
        return hashlib.sha256(key.encode()).hexdigest()

    async def save_report(self, patient_id: str, report: CGMStats):
        try:
            metadata = report.metadata
            report_id = self._generate_report_id(
                patient_id,
                metadata.report_type,
                metadata.date_range.start,
                metadata.date_range.end,
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
                    "created_at": existing_report.get("created_at", now)
                    if existing_report
                    else now,
                    "updated_at": now,
                }
            )

            await self.cgm_report_collection.replace_one(
                {"_id": report_id}, report_dict, upsert=True
            )

            start_dt = self._extract_datetime_from_iso(metadata.date_range.start)
            end_dt = self._extract_datetime_from_iso(metadata.date_range.end)

            logging.info(
                f"Saved/Updated CGM report for {patient_id} from {start_dt} to {end_dt}"
            )

            await self._mark_summaries_stale(
                patient_id=patient_id, start_date=start_dt, end_date=end_dt
            )

            return report_id

        except Exception as error:
            logging.error(f"Failed to save CGM report for {patient_id}: {error}")
            raise

    async def save_reports_bulk(
        self,
        patient_id: str,
        reports: List[CGMStats],
        sensor_status: str = None,
        termination_reason: str = None,
    ):
        from pymongo import UpdateOne

        if not reports:
            logging.warning("No CGM reports to save")
            return None

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

            if report.fitness_report:
                fitness_metadata = report.fitness_report.metadata
                fitness_report_id = self._generate_report_id(
                    patient_id,
                    fitness_metadata.report_type,
                    fitness_metadata.date_range.start,
                    fitness_metadata.date_range.end,
                )
                existing_fitness_report = (
                    await self.fitness_report_service.fetch_report_by_id(
                        fitness_report_id
                    )
                )

                if not existing_fitness_report:
                    fitness_report_id = await self.fitness_report_service.save_report(
                        patient_id, report.fitness_report
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

            if metadata.report_type == CGMReportType.CUSTOM:
                if sensor_status:
                    report_dict["sensor_status"] = sensor_status
                if termination_reason:
                    report_dict["termination_reason"] = termination_reason

            ops.append(
                UpdateOne({"_id": report_id}, {"$set": report_dict}, upsert=True)
            )

        await self.cgm_report_collection.bulk_write(ops)
        logging.info(f"Bulk saved {len(ops)} CGM reports for {patient_id}")

        for report in reports:
            metadata = report.metadata
            start_dt = self._extract_datetime_from_iso(metadata.date_range.start)
            end_dt = self._extract_datetime_from_iso(metadata.date_range.end)
            await self._mark_summaries_stale(
                patient_id=patient_id, start_date=start_dt, end_date=end_dt
            )

        last_report_id = self._generate_report_id(
            patient_id,
            reports[-1].metadata.report_type,
            reports[-1].metadata.date_range.start,
            reports[-1].metadata.date_range.end,
        )
        return last_report_id
