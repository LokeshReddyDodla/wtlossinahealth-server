from lib.utils.retry_utils import retry_request
import openai
from decouple import config

from lib.utils.datetime_utils import convert_milliseconds_to_datetime


def get_nutritional_info(mealtime_ms, image_url, food_description=None, timezone='Asia/Kolkata'):
    openai.api_key = config('OPENAI_API_KEY')
    
    mealtime = convert_milliseconds_to_datetime(mealtime_ms, timezone)

    prompt_text = """
    You are a dietitian expert. Analyze the provided image considering it was taken at {mealtime}. Identify the meal type (e.g., breakfast, lunch, dinner, morning_snack, evening_snack) based on the image and the mealtime. Then, identify all visible food items, provide their coordinates, and give  the nutritional values in the following JSON structure:
    {{
        "meal_type": "<meal type>",
        "items": [
            {{
                "name": "<Dish Name>",
                "coordinates": [<left>, <top>, <right>, <bottom>],
                "serving_size": "<serving size>",
                "serving_quantity": "<serving quantity>",
                "serving_unit": "<serving unit>",
                "nutritional_values": {{
                    "calories": "<calories> kcal",
                    "proteins": "<proteins> g",
                    "carbohydrates": "<carbohydrates> g",
                    "fats": "<fats> g",
                    "fiber": "<fiber> g"
                }}
            }}
        ],
        "total_nutritional_value": {{
            "calories": "<total calories> kcal",
            "proteins": "<total proteins> g",
            "carbohydrates": "<total carbohydrates> g",
            "fats": "<total fats> g",
            "fiber": "<total fiber> g"
        }},
        "feedback": "<personalized feedback>",
        "tags": [
            "<tag1>",
            "<tag2>"
        ]
    }}

    For each item:
    1. Ensure that serving_quantity and serving_unit are consistent with serving_size. For example, if serving_size is '1/2 cup', then serving_quantity should be 0.5 and serving_unit should be 'cup'.
    2. Provide personalized feedback to help the user meet average macronutrient values for the detected meal type.
    3. Suggest similar foods from the same cuisine or region that can help improve or maintain a balanced diet.
    4. Ensure serving sizes are realistic and provided in common units such as grams, cups, or pieces. If unsure, make a best guess.
    5. Add appropriate tags such as 'good meal', 'bad meal', 'healthy meal', or 'unhealthy meal' based on the nutritional analysis.

    Please follow this structure precisely for the response.
    """.format(mealtime=mealtime)

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Act as a dietitian expert."},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }
    ]

    if food_description:
        messages[0]["content"].append({"type": "text", "text": f"Food description: {food_description}"})

    messages[0]["content"].append({"type": "text", "text": prompt_text})

    response = retry_request(
        openai.chat.completions.create,
        max_retries=3,
        delay=2,
        model="gpt-4o",
        messages=messages,
        max_tokens=3000
    )

    return response.choices[0].message.content




    
