"""Pydantic schemas for SMBG report statistics."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DateRange(BaseModel):
    """Date range with ISO formatted dates."""

    start: str = Field(..., description="Start date in ISO format")
    end: str = Field(..., description="End date in ISO format")


class ReportMetadata(BaseModel):
    """Metadata about the report."""

    date_range: DateRange = Field(..., description="Date range for the report")
    total_readings: int = Field(..., description="Total number of SMBG readings")
    days_covered: int = Field(..., description="Number of days covered in the report")


class GlucoseStatistics(BaseModel):
    """Glucose level statistics."""

    count: int = Field(..., description="Number of readings")
    median: Optional[float] = Field(None, description="Median glucose level in mg/dL")
    highest: Optional[float] = Field(None, description="Highest glucose level in mg/dL")
    lowest: Optional[float] = Field(None, description="Lowest glucose level in mg/dL")
    out_of_range_count: int = Field(0, description="Number of readings out of target range")
    average_time_of_day: Optional[str] = Field(
        None, description="Average time of day for readings (HH:MM format)"
    )


class MealWindowGlucoseStats(BaseModel):
    """Glucose statistics for a specific meal window."""

    glucose: GlucoseStatistics = Field(..., description="Glucose statistics")


class MealWindowBreakdown(BaseModel):
    """Breakdown of statistics by meal window."""

    by_meal_window: Dict[str, MealWindowGlucoseStats] = Field(
        ..., description="Statistics grouped by meal window (e.g., pre_breakfast, post_breakfast)"
    )


class MealRangeStats(BaseModel):
    """Statistics for pre-meal or post-meal readings."""

    count: int = Field(..., description="Number of readings")
    within_range_count: int = Field(..., description="Number of readings within target range")
    within_range_percentage: float = Field(
        ..., description="Percentage of readings within target range"
    )


class OverallScore(BaseModel):
    """Overall score for glucose control."""

    pre_meal: float = Field(..., description="Pre-meal score percentage")
    post_meal: float = Field(..., description="Post-meal score percentage")
    overall: float = Field(..., description="Overall score percentage")


class WeeklyTrendPeriod(BaseModel):
    """Period information for weekly trend."""

    start: str = Field(..., description="Week start date in ISO format")
    end: str = Field(..., description="Week end date in ISO format")
    week_number: int = Field(..., description="Week number")
    iso_week_number: int = Field(..., description="ISO week number")


class WeeklyTrendGlucose(BaseModel):
    """Glucose medians for a week."""

    pre_meal: Optional[float] = Field(None, description="Pre-meal median glucose in mg/dL")
    post_meal: Optional[float] = Field(None, description="Post-meal median glucose in mg/dL")


class WeeklyTrend(BaseModel):
    """Weekly trend data."""

    period: WeeklyTrendPeriod = Field(..., description="Week period information")
    glucose_medians: WeeklyTrendGlucose = Field(..., description="Glucose medians for the week")


class MonthlyGlucoseStats(BaseModel):
    """Glucose statistics for a month."""

    total_readings: int = Field(..., description="Total number of readings in the month")
    pre_meal: MealRangeStats = Field(..., description="Pre-meal statistics")
    post_meal: MealRangeStats = Field(..., description="Post-meal statistics")
    overall_score: OverallScore = Field(..., description="Overall glucose control score")
    weekly_trends: Dict[str, WeeklyTrend] = Field(
        ..., description="Weekly trends within the month"
    )


class MonthlyPeriod(BaseModel):
    """Period information for monthly summary."""

    start: str = Field(..., description="Month start date in ISO format")
    end: str = Field(..., description="Month end date in ISO format")
    year: int = Field(..., description="Year")
    month: int = Field(..., description="Month number (1-12)")
    month_name: str = Field(..., description="Month name")


class MonthlySummary(BaseModel):
    """Monthly summary statistics."""

    period: MonthlyPeriod = Field(..., description="Month period information")
    glucose: MonthlyGlucoseStats = Field(..., description="Glucose statistics for the month")
    meal: Any = Field(..., description="Meal statistics for the month (from meal_stats_processor)")


class MonthlyTrends(BaseModel):
    """Monthly trends data."""

    monthly: List[MonthlySummary] = Field(..., description="List of monthly summaries")


class ReportSummary(BaseModel):
    """Overall summary of the report."""

    glucose: GlucoseStatistics = Field(..., description="Overall glucose statistics")
    meal_statistics: Dict[str, Any] = Field(
        default_factory=dict, description="Meal statistics from meal_stats_processor"
    )


class SMBGReadingValue(BaseModel):
    """Individual SMBG reading value."""

    reading_time: str = Field(..., description="Reading timestamp in ISO format")
    glucose_level: float = Field(..., description="Glucose level in mg/dL")
    type: str = Field(..., description="Reading type (e.g., pre_meal, post_meal)")
    source_name: str = Field(..., description="Source name for the reading")
    source_platform: str = Field(..., description="Source platform for the reading")
    notes: Optional[str] = Field(None, description="Optional notes for the reading")


class SMBGDateWiseData(BaseModel):
    """Combined SMBG and meal data for a specific date."""

    smbg_readings: List[SMBGReadingValue] = Field(
        default_factory=list, description="SMBG readings for the date"
    )
    meals: List[Dict[str, Any]] = Field(
        default_factory=list, description="Meals for the date"
    )


class SMBGReport(BaseModel):
    """Complete SMBG report with all statistics."""

    metadata: ReportMetadata = Field(..., description="Report metadata")
    summary: ReportSummary = Field(..., description="Overall summary statistics")
    breakdowns: MealWindowBreakdown = Field(..., description="Breakdowns by meal window")
    trends: MonthlyTrends = Field(..., description="Monthly trends")
    by_date: Dict[str, SMBGDateWiseData] = Field(
        default_factory=dict,
        description="Unified date-wise data with both SMBG readings and meals.",
    )

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "metadata": {
                    "date_range": {
                        "start": "2025-01-01T00:00:00",
                        "end": "2026-01-01T23:59:59",
                    },
                    "total_readings": 150,
                    "days_covered": 366,
                },
                "summary": {
                    "glucose": {
                        "count": 150,
                        "median": 120.5,
                        "highest": 180.0,
                        "lowest": 70.0,
                        "out_of_range_count": 15,
                        "average_time_of_day": "14:30",
                    },
                    "comparison": {
                        "previous_week_median": 115.0,
                    },
                    "meal_statistics": {},
                },
                "breakdowns": {
                    "by_meal_window": {
                        "pre_breakfast": {
                            "glucose": {
                                "count": 30,
                                "median": 100.0,
                                "highest": 120.0,
                                "lowest": 80.0,
                                "out_of_range_count": 2,
                                "average_time_of_day": "08:00",
                            },
                            "comparison": {
                                "previous_week_median": 98.0,
                            },
                        },
                    },
                },
                "trends": {
                    "monthly": [],
                },
                "by_date": {
                    "2025-01-01": {
                        "smbg_readings": [
                            {
                                "reading_time": "2025-01-01T08:00:00",
                                "glucose_level": 105.0,
                                "type": "pre_breakfast",
                                "source_name": "glucometer",
                                "source_platform": "manual",
                                "notes": None,
                            }
                        ],
                        "meals": [
                            {
                                "id": "meal-123",
                                "type": "breakfast",
                                "time": "08:15:00",
                                "score": 8.2,
                            }
                        ],
                    }
                },
            }
        }
