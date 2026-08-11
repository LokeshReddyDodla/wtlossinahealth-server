import hashlib
import logging
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional

from lib.schemas.cgm_stats import CGMStats
from lib.services.patient_summary.enum import StaleReason
from lib.utils.datetime_utils import parse_datetime
from lib.utils.patient_summary_stale import mark_summary_stale_and_enqueue
from .processor import CGMReportType


class CGMReportService:
    def __init__(
        self,
        cgm_report_collection,
        meal_report_service,
        fitness_report_service,
        sleep_report_service,
        patient_summary_service=None,
    ):
        self.cgm_report_collection = cgm_report_collection
        self.meal_report_service = meal_report_service
        self.fitness_report_service = fitness_report_service
        self.sleep_report_service = sleep_report_service
        self.patient_summary_service = patient_summary_service

    async def _mark_summaries_stale_for_range(
        self, patient_id: str, start_date: datetime, end_date: datetime
    ) -> None:
        """Mark summaries as stale and enqueue regeneration for each date in range."""
        try:
            # Iterate through each day in the range
            current_date = start_date.date()
            end_date_obj = end_date.date()

            while current_date <= end_date_obj:
                await mark_summary_stale_and_enqueue(
                    patient_id=patient_id,
                    target_date=current_date,
                    stale_reason=StaleReason.DATA_UPDATED,
                )
                current_date += timedelta(days=1)
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
                    "metadata": 1,
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
                    "metadata": 1,
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
                    "$lookup": {
                        "from": "sleep_reports",
                        "localField": "sleep_report_id",
                        "foreignField": "_id",
                        "as": "sleep_report",
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
                    "$unwind": {
                        "path": "$sleep_report",
                        "preserveNullAndEmptyArrays": True,
                    }
                },
                {
                    "$project": {
                        "meal_report_id": 0,
                        "fitness_report_id": 0,
                        "sleep_report_id": 0,
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
                        "$lookup": {
                            "from": "sleep_reports",
                            "localField": "sleep_report_id",
                            "foreignField": "_id",
                            "as": "sleep_report",
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
                        "$unwind": {
                            "path": "$sleep_report",
                            "preserveNullAndEmptyArrays": True,
                        }
                    },
                    {
                        "$project": {
                            "meal_report_id": 0,
                            "fitness_report_id": 0,
                            "sleep_report_id": 0,
                        }
                    },
                ]
            )

            daily_reports = []
            week_wise = []

            async for report in other_cursor:
                report_type = report.get("metadata", {}).get("report_type", "")
                if report_type == "daily":
                    daily_reports.append(report)
                elif report_type == "weekly":
                    week_wise.append(report)

            week_wise = self._deduplicate_weekly_reports(week_wise)

            return {
                "overall": custom_report,
                "day_wise": daily_reports,
                "week_wise": week_wise,
            }

        except Exception as error:
            logging.error(
                f"Failed to fetch full CGM report for {patient_id} with report_id {report_id}: {error}"
            )
            return None

    def _deduplicate_weekly_reports(self, weekly_reports: List[Dict]) -> List[Dict]:
        """Keep only the latest snapshot for each ISO week.

        Weekly reports are regenerated as custom report end date extends. Old
        snapshots can coexist, so we collapse by ISO week and keep the one
        with the furthest end date.
        """
        latest_by_iso_week: Dict[str, Dict] = {}

        for report in weekly_reports:
            metadata = report.get("metadata", {})
            date_range = metadata.get("date_range", {})
            start_dt = parse_datetime(date_range.get("start"))
            end_dt = parse_datetime(date_range.get("end"))

            if not start_dt:
                continue

            iso = start_dt.isocalendar()
            week_key = f"{iso.year}-W{iso.week:02d}"

            existing = latest_by_iso_week.get(week_key)
            if not existing:
                latest_by_iso_week[week_key] = report
                continue

            existing_end_dt = parse_datetime(
                existing.get("metadata", {}).get("date_range", {}).get("end")
            )
            if end_dt and (not existing_end_dt or end_dt > existing_end_dt):
                latest_by_iso_week[week_key] = report

        return sorted(
            latest_by_iso_week.values(),
            key=lambda report: parse_datetime(
                report.get("metadata", {}).get("date_range", {}).get("start")
            )
            or datetime.min,
        )

    async def fetch_daily_report(self, patient_id: str, date: date):
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
                        "$lookup": {
                            "from": "sleep_reports",
                            "localField": "sleep_report_id",
                            "foreignField": "_id",
                            "as": "sleep_report",
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
                        "$unwind": {
                            "path": "$sleep_report",
                            "preserveNullAndEmptyArrays": True,
                        }
                    },
                    {
                        "$project": {
                            "meal_report_id": 0,
                            "fitness_report_id": 0,
                            "sleep_report_id": 0,
                        }
                    },
                    {"$limit": 1},
                ]
            )
            report = await cursor.to_list(length=1)
            return report[0] if report else None

        except Exception as error:
            logging.error(
                f"Failed to fetch daily report for {patient_id} on {date}: {error}"
            )
            return None

    async def fetch_daily_reports(
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
                        "sleep_report_id": 0,
                    }
                },
            ]

            daily_reports = await self.cgm_report_collection.aggregate(
                pipeline
            ).to_list(length=None)

            if not daily_reports:
                logging.warning(
                    f"No daily CGM reports found for {patient_id} ({start_date} - {end_date})"
                )

            return daily_reports

        except Exception as error:
            logging.error(
                f"Failed to fetch daily CGM reports for {patient_id}: {error}"
            )
            return []

    def _generate_report_id(
        self,
        patient_id: str,
        report_type: str,
        start_iso: str,
        end_iso: str,
        include_end: bool = True,
    ) -> str:
        if include_end:
            key = f"{patient_id}_{report_type}_{start_iso}_{end_iso}"
        else:
            key = f"{patient_id}_{report_type}_{start_iso}"

        return hashlib.sha256(key.encode()).hexdigest()

    def _compute_report_id_from_metadata(self, patient_id: str, metadata) -> str:
        """Compute report id from a metadata object.

        This ensures consistent handling of CUSTOM reports (which are
        deduplicated by start only).
        """
        is_custom = (
            metadata.report_type == CGMReportType.CUSTOM
            or str(metadata.report_type).lower() == "custom"
        )
        include_end = not is_custom
        return self._generate_report_id(
            patient_id,
            metadata.report_type,
            metadata.date_range.start,
            metadata.date_range.end,
            include_end=include_end,
        )

    async def save_report(self, patient_id: str, report: CGMStats):
        try:
            metadata = report.metadata
            report_id = self._compute_report_id_from_metadata(patient_id, metadata)
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

            start_dt = parse_datetime(metadata.date_range.start)
            end_dt = parse_datetime(metadata.date_range.end)

            logging.info(
                f"Saved/Updated CGM report for {patient_id} from {start_dt} to {end_dt}"
            )

            if start_dt and end_dt:
                await self._mark_summaries_stale_for_range(
                    patient_id=patient_id, start_date=start_dt, end_date=end_dt
                )
            else:
                logging.warning(
                    f"Could not parse datetime range for CGM report: {metadata.date_range.start} - {metadata.date_range.end}"
                )

            return report_id

        except Exception as error:
            logging.error(f"Failed to save CGM report for {patient_id}: {error}")
            raise

    async def save_reports_bulk(
        self,
        patient_id: str,
        reports: List[CGMStats],
        sensor_status: Optional[str] = None,
        termination_reason: Optional[str] = None,
    ):
        from pymongo import ReplaceOne  # type: ignore

        if not reports:
            logging.warning("No CGM reports to save")
            return None

        now = datetime.now()
        ops = []

        for report in reports:
            metadata = report.metadata
            report_dict = report.model_dump(exclude_none=True)
            report_id = self._compute_report_id_from_metadata(patient_id, metadata)

            if report.fitness_report:
                fitness_metadata = report.fitness_report.metadata
                # Match by the fitness service's own id scheme so the stored
                # fitness_report_id equals the doc's _id for every report type.
                fitness_report_id = self.fitness_report_service._generate_report_id(
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

            if report.sleep_report:
                sleep_metadata = report.sleep_report.metadata
                # Match by the sleep service's own id scheme so the stored
                # sleep_report_id equals the doc's _id for every report type.
                sleep_report_id = self.sleep_report_service._generate_report_id(
                    patient_id,
                    sleep_metadata.report_type,
                    sleep_metadata.date_range.start,
                    sleep_metadata.date_range.end,
                )
                existing_sleep_report = (
                    await self.sleep_report_service.fetch_report_by_id(
                        sleep_report_id
                    )
                )

                if not existing_sleep_report:
                    sleep_report_id = await self.sleep_report_service.save_report(
                        patient_id, report.sleep_report
                    )

                report_dict["sleep_report_id"] = sleep_report_id
                report_dict.pop("sleep_report", None)

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

            # Full replace: a regenerated report must not inherit fields that
            # exclude_none omits this time but a prior version had set.
            ops.append(
                ReplaceOne({"_id": report_id}, report_dict, upsert=True)
            )

        await self.cgm_report_collection.bulk_write(ops)
        logging.info(f"Bulk saved {len(ops)} CGM reports for {patient_id}")

        for report in reports:
            metadata = report.metadata
            start_dt = parse_datetime(metadata.date_range.start)
            end_dt = parse_datetime(metadata.date_range.end)
            if start_dt and end_dt:
                await self._mark_summaries_stale_for_range(
                    patient_id=patient_id, start_date=start_dt, end_date=end_dt
                )
            else:
                logging.warning(
                    f"Could not parse datetime range for CGM report: {metadata.date_range.start} - {metadata.date_range.end}"
                )

        last_meta = reports[-1].metadata
        last_report_id = self._compute_report_id_from_metadata(patient_id, last_meta)
        return last_report_id
