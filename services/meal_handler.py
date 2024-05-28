from lib.utils.prompt_wrapper import wrap_prompt
import openai
from decouple import config
from lib.utils.retry_utils import retry_request
import logging
from lib.managers.context_manager import context_manager

logger = logging.getLogger(__name__)

def handle_meal_context(message: str, history: list, context_id: str, is_contextual: bool = False) -> str:
    if not context_id:
        raise ValueError("Context ID must be provided")
    
    openai.api_key = config('OPENAI_API_KEY')
    
    if is_contextual:
        # When contextual, respond with minimal information
        prompt_text = wrap_prompt("""
            You are a dietitian expert.
            Ensure the response is correct and short.
        """.strip())
        openai_messages = [{"role": "system", "content": prompt_text}] + history + [{"role": "user", "content": message}]
        openai_messages = [{"role": "user", "content": message}] + history
    else:
        # Define the prompt for the meal context
        prompt_text = wrap_prompt("""
            You are a dietitian expert. Analyze the provided image considering it was taken at a specific mealtime. Identify the meal type (e.g., breakfast, lunch, dinner, morning_snack, evening_snack) based on the image and the mealtime. Then, identify all visible food items and provide a detailed analysis of the meal in a well-structured paragraph. Include the following points:
            1. The meal type.
            2. A summary of all visible food items.
            3. The nutritional values of the meal (total calories, proteins, carbohydrates, fats, and fiber).
            4. Personalized feedback to help the user meet average macronutrient values for the detected meal type.
            5. Suggestions for similar foods from the same cuisine or region that can help improve or maintain a balanced diet.
            6. Appropriate tags such as 'good meal', 'bad meal', 'healthy meal', or 'unhealthy meal' based on the nutritional analysis.
            Ensure the response is short and is easy to understand.
        """.strip())
        # Prepare messages for the OpenAI request, including the image URL
        openai_messages = [
            {"role": "system", "content": prompt_text}] + history + [
            {"role": "user", "content": [
                {"type": "text", "text": "Act as a dietitian expert."},
                {"type": "image_url", "image_url": {"url": message}}]}
        ]
        
    response = retry_request(
        openai.chat.completions.create,
        max_retries=3,
        delay=2,
        model="gpt-4o",
        messages=openai_messages,
        max_tokens=3000
    )

    # Add the assistant's response to the conversation history
    assistant_message = response.choices[0].message.content
    history.append({"role": "assistant", "content": assistant_message})
    logger.info("Assistant message added to history for context %s: %s", context_id, assistant_message)
    
    # save the conversation history to the file
    context_manager.save_context_history_to_file(context_id, history)
    
    return assistant_message
