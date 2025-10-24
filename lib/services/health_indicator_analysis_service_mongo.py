"""
Health Indicator Analysis Service - MongoDB Version

This service analyzes health indicators from inbody measurements stored in MongoDB.
All data is read from and written to MongoDB collections.
"""

from typing import Dict, List, Optional
from datetime import datetime
from uuid import UUID
from motor.motor_asyncio import AsyncIOMotorCollection

from lib.core.mongo_store import MongoStore


class HealthIndicatorAnalysisService:
    """Service for AI-powered analysis of health indicators from inbody measurements - MongoDB"""

    def __init__(
        self,
        reports_collection: AsyncIOMotorCollection,
        enrollments_collection: AsyncIOMotorCollection
    ):
        self.reports_collection = reports_collection
        self.enrollments_collection = enrollments_collection

    async def analyze_health_indicators(
        self,
        measurements: List[Dict],
        patient: Dict
    ) -> List[Dict]:
        """
        Analyze measurements and create health indicators with basic analysis
        
        Args:
            measurements: List of measurement dictionaries from MongoDB
            patient: Patient data dictionary
            
        Returns:
            List of health indicator dictionaries
        """

        health_indicators = []

        for measurement in measurements:
            # Use the normal ranges from the measurement
            normal_min = measurement.get("normal_min")
            normal_max = measurement.get("normal_max")

            # Determine if measurement is abnormal
            is_abnormal = False
            abnormality_level = None
            measurement_type = measurement.get("measurement_type", "Unknown")
            value = measurement.get("value", 0)
            unit = measurement.get("unit", "")
            
            analysis_explanation = f"Measurement {measurement_type}: {value} {unit}"

            if normal_min is not None and normal_max is not None:
                if value < normal_min:
                    is_abnormal = True
                    abnormality_level = "low"
                    analysis_explanation += f" (below normal range {normal_min}-{normal_max})"
                elif value > normal_max:
                    is_abnormal = True
                    abnormality_level = "high"
                    analysis_explanation += f" (above normal range {normal_min}-{normal_max})"
                else:
                    analysis_explanation += f" (within normal range {normal_min}-{normal_max})"

            # Create health indicator dictionary (MongoDB document structure)
            health_indicator = {
                "indicator_name": measurement_type,
                "indicator_type": "measurement",
                "value": value,
                "unit": unit,
                "is_abnormal": is_abnormal,
                "abnormality_level": abnormality_level,
                "normal_range_min": normal_min,
                "normal_range_max": normal_max,
                "analysis_explanation": analysis_explanation,
                "recommendations": self._generate_recommendations(
                    measurement_type, value, is_abnormal, abnormality_level
                ) if is_abnormal else None
            }

            health_indicators.append(health_indicator)

        return health_indicators

    def _generate_recommendations(
        self,
        measurement_type: str,
        value: float,
        is_abnormal: bool,
        abnormality_level: Optional[str]
    ) -> str:
        """Generate basic recommendations based on measurement type and abnormality"""
        
        if not is_abnormal:
            return "Measurement is within normal range. Continue current health practices."
        
        measurement_lower = measurement_type.lower()
        
        # BMI recommendations
        if "bmi" in measurement_lower:
            if abnormality_level == "high":
                return "BMI is elevated. Consider a balanced diet with regular exercise. Consult with your healthcare provider for personalized guidance."
            else:
                return "BMI is below normal range. Consider increasing caloric intake with nutritious foods. Consult with a healthcare provider."
        
        # Body fat recommendations
        if "body fat" in measurement_lower or "fat" in measurement_lower:
            if abnormality_level == "high":
                return "Body fat percentage is elevated. Focus on cardiovascular exercise and strength training. Consider consulting with a nutritionist."
            else:
                return "Body fat percentage is low. Ensure adequate nutrition and consult with a healthcare provider if concerned."
        
        # Weight recommendations
        if "weight" in measurement_lower:
            if abnormality_level == "high":
                return "Weight is above target range. Consider portion control, regular exercise, and consultation with a healthcare provider."
            else:
                return "Weight is below target range. Focus on nutrient-dense foods and consult with a healthcare provider."
        
        # Muscle mass recommendations
        if "muscle" in measurement_lower:
            if abnormality_level == "low":
                return "Muscle mass is below optimal range. Consider resistance training and adequate protein intake."
            else:
                return "Muscle mass is above normal range. Maintain current exercise routine and ensure balanced nutrition."
        
        # Generic recommendation
        return f"{measurement_type} is {abnormality_level}. Consult with your healthcare provider for personalized recommendations."

    async def get_report_with_indicators(
        self,
        report_id: str
    ) -> Optional[Dict]:
        """
        Get a report with all its health indicators
        
        Args:
            report_id: UUID string of the report
            
        Returns:
            Report document with embedded health_indicators array
        """
        return await self.reports_collection.find_one({"report_id": report_id})

    async def get_abnormal_indicators_for_enrollment(
        self,
        enrollment_id: str,
        limit: int = 10
    ) -> List[Dict]:
        """
        Get all abnormal health indicators for an enrollment
        
        Args:
            enrollment_id: UUID string of the enrollment
            limit: Maximum number of indicators to return
            
        Returns:
            List of reports with abnormal indicators
        """
        pipeline = [
            # Match reports for this enrollment
            {"$match": {"enrollment_id": enrollment_id}},
            # Sort by report date (most recent first)
            {"$sort": {"report_date": -1}},
            # Limit number of reports
            {"$limit": limit},
            # Unwind health indicators array
            {"$unwind": "$health_indicators"},
            # Filter only abnormal indicators
            {"$match": {"health_indicators.is_abnormal": True}},
            # Group back
            {
                "$group": {
                    "_id": "$report_id",
                    "report_date": {"$first": "$report_date"},
                    "abnormal_indicators": {"$push": "$health_indicators"}
                }
            },
            # Sort by date again
            {"$sort": {"report_date": -1}}
        ]
        
        cursor = self.reports_collection.aggregate(pipeline)
        return await cursor.to_list(length=None)

    async def get_indicator_trends(
        self,
        enrollment_id: str,
        indicator_name: str,
        limit: int = 10
    ) -> List[Dict]:
        """
        Get trend data for a specific health indicator across multiple reports
        
        Args:
            enrollment_id: UUID string of the enrollment
            indicator_name: Name of the indicator to track
            limit: Maximum number of data points
            
        Returns:
            List of indicator values over time
        """
        pipeline = [
            # Match reports for this enrollment
            {"$match": {"enrollment_id": enrollment_id}},
            # Sort by report date
            {"$sort": {"report_date": -1}},
            # Limit number of reports
            {"$limit": limit},
            # Unwind health indicators
            {"$unwind": "$health_indicators"},
            # Filter by indicator name
            {"$match": {"health_indicators.indicator_name": indicator_name}},
            # Project needed fields
            {
                "$project": {
                    "report_date": 1,
                    "value": "$health_indicators.value",
                    "unit": "$health_indicators.unit",
                    "is_abnormal": "$health_indicators.is_abnormal",
                    "abnormality_level": "$health_indicators.abnormality_level"
                }
            },
            # Sort by date ascending for trend
            {"$sort": {"report_date": 1}}
        ]
        
        cursor = self.reports_collection.aggregate(pipeline)
        return await cursor.to_list(length=None)
