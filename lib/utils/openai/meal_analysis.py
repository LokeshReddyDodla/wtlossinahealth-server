import openai
from decouple import config


def get_nutritional_info(image_url, food_description=None):
    openai.api_key = config('OPENAI_API_KEY')
    
    prompt_text = """Analyze the provided image and identify all visible food items. For each item identified, and for the total meal, return the nutritional values in the following JSON structure:
        {
        "items": [
            {
            "name": "<Dish Name>",
            "nutritional_values": {
                "calories": "<calories> kcal",
                "proteins": "<proteins> g",
                "carbohydrates": "<carbohydrates> g",
                "fats": "<fats> g",
                "fiber": "<fiber> g"
            }
            }
        ],
        "total_nutritional_value": {
            "calories": "<total calories> kcal",
            "proteins": "<total proteins> g",
            "carbohydrates": "<total carbohydrates> g",
            "fats": "<total fats> g"
        }
        }

        Please follow this structure precisely for the response."""


    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Act as a calorie counter."},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }
    ]

    if food_description:
        messages[0]["content"].append({"type": "text", "text": f"Food description: {food_description}"})

    messages[0]["content"].append({"type": "text", "text": prompt_text})

    response = openai.chat.completions.create(
        model="gpt-4-vision-preview",
        messages=messages,
        max_tokens=1000,
    )

    return response.choices[0].message.content




    
