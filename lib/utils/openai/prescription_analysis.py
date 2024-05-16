import openai
from decouple import config
from typing import Optional, Union
from lib.utils.retry_utils import retry_request
from lib.utils.datetime_utils import convert_milliseconds_to_datetime

def analyse_prescription(image_url: str):
    openai.api_key = config('OPENAI_API_KEY')

    prompt_text = """
    You are an expert in analyzing prescription images. Analyze the provided image and extract the following structured information if it is a valid prescription:
    {{
        "prescription_valid": true,
        "doctor_name": "<doctor name>",
        "patient_name": "<patient name>",
        "prescription_date": "<prescription date>",
        "medicines": [
            {{
                "name": "<medicine name>",
                "dosage": "<dosage>",
                "frequency": "<frequency>",
                "duration": "<duration>",
                "purpose": "<what this medicine is for>",
                "effects": "<potential effects>"
            }}
        ]
    }}

    If the image is not a prescription, respond with:
    {{
        "prescription_valid": false,
        "message": "The provided image is not a prescription."
    }}

    Please follow this structure precisely for the response.
    """

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Act as a prescription analysis expert."},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }
    ]

    messages[0]["content"].append({"type": "text", "text": prompt_text})

    response = retry_request(
        openai.chat.completions.create,
        max_retries=3,
        delay=2,
        model="gpt-4o",
        messages=messages,
        max_tokens=1000
    )

    return response.choices[0].message.content
