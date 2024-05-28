import openai
from decouple import config
from lib.utils.retry_utils import retry_request
import logging

logger = logging.getLogger(__name__)

def handle_report_context(message: str, history: list, context_id: str) -> str:
    openai.api_key = config('OPENAI_API_KEY')

    # Define the prompt for the report context
    prompt = "You are an experienced endocrinologist."

    response = retry_request(
        openai.chat.completions.create,
        max_retries=3,
        delay=2,
        model="gpt-4o",
        messages=[{"role": "system", "content": prompt}] + history,
        max_tokens=3000
    )

    # Add the assistant's response to the conversation history
    assistant_message = response.choices[0].message.content
    history.append({"role": "assistant", "content": assistant_message})
    logger.info("Assistant message added to history for context %s: %s", context_id, assistant_message)
    
    return assistant_message
