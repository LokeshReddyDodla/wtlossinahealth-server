import asyncio
from datetime import date

from celery import shared_task

from lib.utils.async_runner import run_async_task


# @shared_task
# def generate_daily_meal_report(
#     patient_id: str,
#     report_date: date,
# ):
#     try:
#         from lib.dependencies.service_dependencies import (
#             get_meal_report_service,
#             get_meal_stats_processor,
#         )

#         processor = get_meal_stats_processor()
#         service = get_meal_report_service()

#         async def generate_and_save_report():
#             # Generate the meal report
#             report = await processor.get_meal_report_by_date(
#                 patient_id, report_date
#             )

#             # Save the meal report
#             await service.save_report(
#                 patient_id,
#                 {
#                     "patient_id": patient_id,
#                     "report_type": "daily",
#                     **report.model_dump(),
#                 },
#             )

#         loop = asyncio.get_event_loop()
#         loop.run_until_complete(generate_and_save_report())

#         print(
#             f"✅ Successfully generated meal report for {patient_id} on {report_date}"
#         )

#     except Exception as error:
#         print(
#             f"❌ Failed to generate meal report for {patient_id} on {report_date}. Error: {error}"
#         )


@shared_task
def generate_daily_meal_report(
    patient_id: str,
    report_date: date,
):
    try:
        from lib.dependencies.service_dependencies import (
            get_meal_report_service,
            get_meal_stats_processor,
        )
        import asyncio
        from datetime import datetime

        # Create new event loop for this task
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            processor = get_meal_stats_processor()
            service = get_meal_report_service()

            # Generate report
            report = loop.run_until_complete(
                processor.get_meal_report_by_date(patient_id, report_date)
            )

            # Save report
            loop.run_until_complete(
                service.save_report(
                    patient_id,
                    {
                        "patient_id": patient_id,
                        "report_type": "daily",
                        **report.model_dump(),
                    },
                )
            )

            print(
                f"✅ Successfully generated meal report for {patient_id} on {report_date}"
            )
            return True

        finally:
            loop.close()
        pass
    except Exception as error:
        print(f"❌ Failed to generate meal report: {error}")
