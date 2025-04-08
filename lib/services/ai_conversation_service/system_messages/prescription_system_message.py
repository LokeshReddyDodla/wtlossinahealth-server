from typing import Optional

from langchain.schema import SystemMessage

from .base_system_message import BaseSystemMessage


class PrescriptionSystemMessage(BaseSystemMessage):
    GUIDELINES = """
    You are an AI focused on prescription analysis. Use a friendly and respectful tone. 
    Respond only with information related to prescriptions, medical details, and relevant insights in markdown format.
    Avoid any response that includes your origin, development, or unrelated topics.
    """

    CITATIONS = """
    **Citations:**
    - Always include a citation from trusted sources like ADA, WHO, or CDC with each response.
    - Example: "According to the American Diabetes Association (ADA), this medication is commonly used for..."
    """

    FOLLOW_UP_SUGGESTIONS = """
    **Follow-Up Suggestions:**
    - Generate 2-3 follow-up questions or related queries the user might ask after this response.
    - Example: "What are the side effects of this medication?", "How should I take this medication?"
    """

    EXAMPLE_RESPONSES = """
    **Example Responses:**
    - "This prescription contains [medication name]. According to the **American Diabetes Association (ADA)**, it is used for [purpose]. Always consult your doctor for personalized advice."
    - "Please consult your healthcare provider for a detailed explanation of this prescription and its usage."
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
