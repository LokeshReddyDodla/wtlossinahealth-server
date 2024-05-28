from lib.utils.prompt_wrapper import wrap_prompt
import openai
from decouple import config
from lib.utils.retry_utils import retry_request
import logging
from lib.managers.context_manager import context_manager

logger = logging.getLogger(__name__)

def handle_meal_context(message: str, history: list, context_id: str, media_url) -> str:
    if not context_id:
        raise ValueError("Context ID must be provided")
    
    openai.api_key = config('OPENAI_API_KEY')
    
    prompt_text = wrap_prompt("""
        You are a dietitian expert. Provide a concise and accurate response.
    """.strip())
    
    openai_messages = [
        {"role": "system", "content": prompt_text}
    ] 
    
    if media_url:
        openai_messages += [
        {
            "role": "user", "content": [
                {"type": "text", "text": "Act as a dietitian expert. Analyze the provided image and Provide a concise and accurate response."},
                {"type": "image_url", "image_url": {"url": media_url}}
            ]
        }
    ]
        
    openai_messages +=  history + [
        {"role": "user", "content": message}]
    
 
    logger.info("==> openai_messages: %s", openai_messages)
        
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
    context_manager.add_message(context_id,  assistant_message, "assistant")
    logger.info("Assistant message added to history for context %s: %s", context_id, assistant_message)
    
    # save the conversation history to the file
    context_manager.save_context_history_to_file(context_id, history)
    
    return assistant_message
