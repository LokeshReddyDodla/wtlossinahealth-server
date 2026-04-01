"""Daily report aggregation mixin for weight loss agent workflows."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, func
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.models.patient_meal import PatientMeal


class DailyReportsMixin:
    async def get_daily_reports_data(
        self,
        patient_id: UUID,
        start_date: datetime,
        end_date: datetime,
    ) -> List[Dict]:
        """Get daily meal and fitness reports for a patient"""

        async with self.postgres_store.get_session() as session:
            daily_data = []

            # Get date range
            current_date = start_date.date()
            end_date_only = end_date.date()

            while current_date <= end_date_only:
                date_str = current_date.isoformat()

                # Get meals for the day
                meals_result = await session.execute(
                    select(PatientMeal)
                    .where(
                        and_(
                            PatientMeal.patient_id == patient_id,
                            func.date(PatientMeal.date) == current_date,
                        )
                    )
                    .options(
                        selectinload(PatientMeal.total_macro_nutritional_value),
                        selectinload(PatientMeal.total_micro_nutritional_value),
                    )
                )
                meals = meals_result.scalars().all()

                _vitals_query = f"""
                SELECT type, value FROM aihealth.vitals_data
                WHERE patient_id = '{patient_id}'
                    AND toDate(time) = '{current_date}'
                ORDER BY time DESC
                LIMIT 1 BY type
                """
                _vitals_rows = self.clickhouse_store.client.execute(_vitals_query)
                _vitals_map = {r[0]: r[1] for r in _vitals_rows}

                # Get fitness data from external service (placeholder)
                fitness_data = await self._get_fitness_data_for_date(
                    patient_id, current_date
                )

                daily_data.append(
                    {
                        "date": date_str,
                        "meal_data": (
                            {
                                "meals_count": len(meals),
                                "total_calories": sum(
                                    meal.total_macro_nutritional_value.calories
                                    for meal in meals
                                    if meal.total_macro_nutritional_value
                                    and hasattr(
                                        meal.total_macro_nutritional_value,
                                        "calories",
                                    )
                                ),
                                "meals": [
                                    {
                                        "meal_id": str(meal.id),
                                        "type": meal.type,
                                        "calories": (
                                            meal.total_macro_nutritional_value.calories
                                            if meal.total_macro_nutritional_value
                                            else 0
                                        ),
                                    }
                                    for meal in meals
                                ],
                            }
                            if meals
                            else None
                        ),
                        "fitness_data": fitness_data,
                        "vitals_data": (
                            {
                                "weight": _vitals_map.get("weight"),
                                "blood_pressure": (
                                    {
                                        "systolic": _vitals_map.get("systolic_bp"),
                                        "diastolic": _vitals_map.get("diastolic_bp"),
                                    }
                                    if "systolic_bp" in _vitals_map or "diastolic_bp" in _vitals_map
                                    else None
                                ),
                            }
                            if _vitals_map
                            else None
                        ),
                    }
                )

                current_date += timedelta(days=1)

            return daily_data

    async def _get_fitness_data_for_date(
        self, patient_id: UUID, date: date
    ) -> Optional[Dict]:
        """Get fitness data for a specific date from ClickHouse"""

        try:
            # Format date for ClickHouse query
            start_datetime = f"{date.isoformat()} 00:00:00"
            end_datetime = f"{date.isoformat()} 23:59:59"

            # Query to get fitness data for the specific date
            query = f"""
            SELECT
                SUM(CASE WHEN type = 'STEPS' THEN value ELSE 0 END) AS total_steps,
                SUM(CASE WHEN type = 'ACTIVE_ENERGY_BURNED' THEN value ELSE 0 END) AS total_active_energy,
                SUM(dateDiff('minute', start_datetime, end_datetime)) AS total_active_duration
            FROM
                aihealth.fitness_data
            WHERE
                patient_id = '{str(patient_id)}'
                AND start_datetime >= '{start_datetime}'
                AND end_datetime <= '{end_datetime}'
            """

            result = self.clickhouse_store.client.execute(query)

            if result and len(result) > 0:
                steps, active_energy, active_duration = result[0]

                # Only return data if there's actual fitness data
                if steps > 0 or active_energy > 0 or active_duration > 0:
                    return {
                        "steps": int(steps) if steps else 0,
                        "active_energy": (
                            float(active_energy) if active_energy else 0.0
                        ),
                        "active_duration": (
                            int(active_duration) if active_duration else 0
                        ),
                    }

            # Return None if no data found
            return None

        except Exception as e:
            # Log error but don't fail the entire request
            print(
                f"Error fetching fitness data for {patient_id} on {date}: {str(e)}"
            )
            return None
