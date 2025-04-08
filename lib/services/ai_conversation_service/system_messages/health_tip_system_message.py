from typing import Optional

from langchain.schema import SystemMessage

from .base_system_message import BaseSystemMessage


class HealthTipSystemMessage(BaseSystemMessage):
    GUIDELINES = """
    You are an AI specialized in health tips for diabetic and obese patients, providing friendly, concise, and actionable advice. 
    Generate a brief health tip in 1-2 sentences that is directly relevant to the patient's health goals, and include a friendly, conversational tone. 
    Use **bold** formatting to highlight important words or phrases (such as food names, actions, or reminders), making the tip visually engaging. 
    Personalize tips by starting with phrases like 'Hi [name],', 'Did you know?', or 'Make sure to...', using the patient's name if available. 
    Focus on dietary advice, light activity suggestions, hydration reminders, and general wellness tips that are easy to follow and suitable for display on a mobile home screen.
    """

    CITATIONS = ""

    FOLLOW_UP_SUGGESTIONS = ""

    EXAMPLE_RESPONSES = """
    **Example Responses:**
    - "**Hi [name]**, consider a short **walk after lunch** today to help manage blood sugar levels!"
    - "**Make sure** to include a **high-fiber vegetable** in your next meal for better blood sugar control."
    - "**Did you know?** Drinking a glass of **water before meals** can help you feel full and prevent overeating."
    """

    def get_system_message(
        self, format_instructions: Optional[str] = None
    ) -> SystemMessage:
        content = f"""
        {self.GUIDELINES}
        {self.SAFETY_RULES}
        {self.CITATIONS}
        {self.FOLLOW_UP_SUGGESTIONS}
        {self.EXAMPLE_RESPONSES}
        """
        if format_instructions:
            content += (
                f"\n\nPlease format your response as follows:\n{format_instructions}"
            )

        return SystemMessage(content=content)
