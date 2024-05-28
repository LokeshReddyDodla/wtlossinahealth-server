# services/report_analysis_service.py
import openai
from decouple import config
from lib.utils.retry_utils import retry_request

def analyse_report(text: str) -> str:
    openai.api_key = config('OPENAI_API_KEY')
    
    prompt_text = f"""
    You are an expert in medical report analysis. Analyze the following medical report and provide a detailed explanation for the patient:
    {text}
    """

    response = retry_request(
        openai.chat.completions.create,
        max_retries=3,
        delay=2,
        model="gpt-4-turbo",
        messages=[
            {
                "role": "user",
                "content": prompt_text
            }
        ],
        max_tokens=3000
    )

    return response.choices[0].message['content']
