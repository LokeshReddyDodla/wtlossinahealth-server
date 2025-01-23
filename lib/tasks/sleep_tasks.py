from datetime import datetime

from celery import shared_task

from lib.core.types import SleepReportTypeLiteral
from lib.utils.date_utils import get_month_start_end, get_months_between_dates


@shared_task
def generate_sleep_reports_for_patient(
    patient_id: str, start_date: datetime, end_date: datetime
):
    try:
        months_between = get_months_between_dates(start_date, end_date)

        for year, month in reversed(months_between):
            start_date, end_date = get_month_start_end(year, month)

            generate_sleep_report_for_month.delay(
                patient_id, start_date, end_date
            )

        print(f"Generated sleep report for patient: {patient_id}")
    except Exception as e:
        print(f"Failed to generate sleep report for {patient_id}. Error: {e}")


@shared_task
def generate_sleep_report_for_month(
    patient_id: str, start_date: datetime, end_date: datetime
):
    try:
        from lib.core.container import container

        # fitness_stats_service = cast(
        #     FitnessStatsProcessor, container.resolve(FitnessStatsProcessor)
        # )
        # fitness_report_service = cast(
        #     FitnessReportService, container.resolve(FitnessReportService)
        # )
        # # Generate report for the specific month
        # report = fitness_stats_service.generate_report(
        #     patient_id,
        #     start_date,
        #     end_date,
        #     include_overall=True,
        #     include_week_wise=True,
        #     include_day_wise=True,
        # )
        # Prepare reports for bulk saving
        # bulk_reports = []
        # bulk_reports.append(
        #     {
        #         "patient_id": patient_id,
        #         "report_type": "monthly",
        #         **report["overall"].model_dump(),
        #     }
        # )
        # bulk_reports.extend(
        #     [
        #         {
        #             "patient_id": patient_id,
        #             "report_type": "weekly",
        #             **week_stat.model_dump(),
        #         }
        #         for week_stat in report["week_wise"]
        #     ]
        # )
        # bulk_reports.extend(
        #     [
        #         {
        #             "patient_id": patient_id,
        #             "report_type": "daily",
        #             **day_stat.model_dump(),
        #         }
        #         for day_stat in report["day_wise"]
        #     ]
        # )
        # async def save_fitness_report():
        #     await fitness_report_service.save_reports_bulk(bulk_reports)
        # Save reports
        # loop = asyncio.get_event_loop()
        # loop.run_until_complete(save_fitness_report())

        print(
            f"Generated sleep report for {patient_id} from {start_date}-{end_date}"
        )
    except Exception as e:
        print(
            f"Failed to generate sleep report for {patient_id} from {start_date}-{end_date}. Error: {e}"
        )


@shared_task
def generate_sleep_report(
    patient_id: str,
    start_date: datetime,
    end_date: datetime,
    report_type: SleepReportTypeLiteral,
):
    try:
        from lib.core.container import container

        # fitness_stats_service = cast(
        #     FitnessStatsProcessor, container.resolve(FitnessStatsProcessor)
        # )
        # fitness_report_service = cast(
        #     FitnessReportService, container.resolve(FitnessReportService)
        # )
        # report = fitness_stats_service.generate_report(
        #     patient_id,
        #     start_date,
        #     end_date,
        #     include_overall=True,
        #     include_day_wise=report_type in ["weekly", "monthly"],
        # )
        # bulk_reports = []
        # bulk_reports.append(
        #     {
        #         "patient_id": patient_id,
        #         "report_type": report_type,
        #         **report["overall"].model_dump(),
        #     }
        # )
        # if report_type in ["weekly", "monthly"]:
        #     bulk_reports.extend(
        #         [
        #             {
        #                 "patient_id": patient_id,
        #                 "report_type": "daily",
        #                 **day_stat.model_dump(),
        #             }
        #             for day_stat in report["day_wise"]
        #         ]
        #     )
        # async def save_fitness_report():
        #     await fitness_report_service.save_reports_bulk(bulk_reports)
        # # Save reports
        # loop = asyncio.get_event_loop()
        # loop.run_until_complete(save_fitness_report())

        print(
            f"Generated {report_type} sleep report for {patient_id} from {start_date} to {end_date}"
        )

    except Exception as e:
        print(
            f"Failed to generate {report_type} report for {patient_id} from {start_date} to {end_date}. Error: {e}"
        )
