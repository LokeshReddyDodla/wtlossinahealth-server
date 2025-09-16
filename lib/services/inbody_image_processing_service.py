import re
from typing import Dict, List, Optional, Tuple
from PIL import Image
import io
import base64

from lib.utils.s3_utils import S3Utils
from openai import AsyncOpenAI


class InbodyImageProcessingService:
    """Service for processing inbody report images and extracting measurements using GPT-4o"""

    def __init__(self):
        self.s3_utils = S3Utils()
        self.client = AsyncOpenAI()

        # GPT-4o vision prompt for inbody report analysis
        self.inbody_extraction_prompt = """
        You are a medical data extraction specialist. Analyze this Inbody report image and extract all measurable health metrics.

        IMPORTANT: For each measurement, extract the numerical value, its unit, and the normal range (min and max) if available on the report.

        Look for these specific measurements in the image:
        - Weight (in kg)
        - Height (in cm)
        - BMI (Body Mass Index)
        - Body Fat Percentage (%)
        - Skeletal Muscle Mass (kg)
        - Body Water Percentage (%)
        - Bone Mineral Content (kg)
        - Visceral Fat Level
        - Basal Metabolic Rate (kcal)
        - Waist-Hip Ratio (if available)
        - Lean Body Mass (kg)
        - Body Fat Mass (kg)

        Return the data in this exact JSON format:
        {
            "measurements": [
                {
                    "type": "weight",
                    "value": 75.5,
                    "unit": "kg",
                    "normal_min": 55.0,
                    "normal_max": 75.0
                },
                {
                    "type": "bmi",
                    "value": 24.8,
                    "unit": "",
                    "normal_min": 18.5,
                    "normal_max": 24.9
                }
            ],
            "confidence_score": 0.95,
            "extraction_notes": "Any observations about the image quality or extracted data"
        }

        Rules:
        1. Only extract values that are clearly visible in the image
        2. Use exact numerical values from the report
        3. Include units as they appear (kg, %, cm, kcal, etc.)
        4. If a normal range is provided for a measurement, extract the min and max values. If not, set them to null.
        5. Set confidence_score between 0.0 and 1.0 based on clarity and completeness
        6. If a measurement is not found, don't include it in the array
        """

    async def process_inbody_image(self, image_url: str) -> Tuple[List[Dict], float]:
        """
        Process inbody image and extract measurements using GPT-4o vision

        Args:
            image_url: S3 URL of the inbody image

        Returns:
            Tuple of (measurements_list, confidence_score)
        """

        try:
            # Download image from S3
            image_data = await self.s3_utils.download_file(image_url)
            image = Image.open(io.BytesIO(image_data))

            # Convert image to base64 for GPT-4o vision
            base64_image = self._image_to_base64(image)

            # Use GPT-4o vision to extract measurements
            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": self.inbody_extraction_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=1000,
                temperature=0.1,  # Low temperature for consistent extraction
            )

            # Parse the response
            result_text = response.choices[0].message.content
            measurements, confidence_score = self._parse_gpt_response(result_text)

            return measurements, confidence_score

        except Exception as e:
            print(f"Error processing inbody image with GPT-4o: {e}")
            # Return empty measurements with low confidence
            return [], 0.0

    def _image_to_base64(self, image: Image.Image) -> str:
        """Convert PIL Image to base64 string for GPT-4o vision"""

        # Convert to RGB if necessary
        if image.mode != 'RGB':
            image = image.convert('RGB')

        # Save to bytes buffer
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', quality=95)
        image_bytes = buffer.getvalue()

        # Convert to base64
        base64_string = base64.b64encode(image_bytes).decode('utf-8')

        return base64_string

    def _parse_gpt_response(self, response_text: str) -> Tuple[List[Dict], float]:
        """Parse GPT-4o response and extract measurements and confidence score"""

        try:
            import json

            # Try to extract JSON from the response
            # GPT might wrap it in markdown code blocks
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1

            if json_start != -1 and json_end != -1:
                json_str = response_text[json_start:json_end]
                data = json.loads(json_str)
            else:
                # Fallback: try to parse the entire response as JSON
                data = json.loads(response_text)

            measurements = data.get('measurements', [])
            confidence_score = data.get('confidence_score', 0.5)

            # Validate measurements format
            validated_measurements = []
            for measurement in measurements:
                if all(key in measurement for key in ['type', 'value', 'unit']):
                    try:
                        # Ensure value is a number
                        measurement['value'] = float(measurement['value'])
                        measurement['normal_min'] = float(measurement.get('normal_min')) if measurement.get('normal_min') is not None else None
                        measurement['normal_max'] = float(measurement.get('normal_max')) if measurement.get('normal_max') is not None else None
                        validated_measurements.append(measurement)
                    except (ValueError, TypeError):
                        continue

            return validated_measurements, min(max(confidence_score, 0.0), 1.0)

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"Error parsing GPT response: {e}")
            print(f"Response text: {response_text}")
            return [], 0.0

    async def validate_inbody_image(self, image_url: str) -> bool:
        """Validate if uploaded image is likely an inbody report using GPT-4o"""

        try:
            # Download and prepare image
            image_data = await self.s3_utils.download_file(image_url)
            image = Image.open(io.BytesIO(image_data))
            base64_image = self._image_to_base64(image)

            # Use GPT-4o to validate the image
            validation_prompt = """
            Analyze this image and determine if it appears to be an Inbody body composition report.

            Look for these characteristics of a genuine Inbody report:
            - Inbody branding/logo
            - Body composition measurements (weight, BMI, body fat %, muscle mass, etc.)
            - Medical/health data format
            - Professional medical report appearance
            - Measurements in kg, %, cm units
            - Bioelectrical impedance analysis data

            Respond with a JSON object in this exact format:
            {
                "is_inbody_report": true/false,
                "confidence_score": 0.0-1.0,
                "reasoning": "brief explanation"
            }
            """

            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": validation_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=200,
                temperature=0.1,
            )

            result_text = response.choices[0].message.content

            # Parse validation response
            import json
            json_start = result_text.find('{')
            json_end = result_text.rfind('}') + 1

            if json_start != -1 and json_end != -1:
                json_str = result_text[json_start:json_end]
                data = json.loads(json_str)
            else:
                data = json.loads(result_text)

            is_valid = data.get('is_inbody_report', False)
            confidence = data.get('confidence_score', 0.0)

            # Require both positive validation and sufficient confidence
            return is_valid and confidence > 0.6

        except Exception as e:
            print(f"Error validating inbody image: {e}")
            return False

    def get_supported_measurements(self) -> List[str]:
        """Get list of supported measurement types"""

        return [
            "weight", "height", "bmi", "body_fat", "muscle_mass",
            "body_water", "bone_mineral", "visceral_fat",
            "basal_metabolic_rate", "waist_hip_ratio",
            "lean_body_mass", "body_fat_mass"
        ]
