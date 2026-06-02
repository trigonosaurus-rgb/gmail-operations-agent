import os
import logging
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

class EmailAnalysis(BaseModel):
    """Schema for extracting actionable data from an email."""
    is_important: bool = Field(description="True if the email contains critical information, urgent requests, or important news.")
    priority: str = Field(description="Priority level of the email: 'Low', 'Medium', or 'High'.")
    task_required: bool = Field(description="True if the email contains an actionable item that requires creating a task.")
    task_title: Optional[str] = Field(None, description="A concise, descriptive title for the task (if task_required is True).")
    task_description: Optional[str] = Field(None, description="Detailed description of the task based on the email content.")
    summary: str = Field(description="A short 1-2 sentence summary of the email content.")
    category: Optional[str] = Field(None, description="Category of the email (e.g., 'Lead', 'Invoice', 'Newsletter', 'Personal').")
    draft_reply_required: bool = Field(description="True if the email explicitly asks a question or requires a response.")
    draft_reply: Optional[str] = Field(None, description="A polite, context-aware draft reply (if draft_reply_required is True).")


class AIAnalyzer:
    """Uses OpenAI API (e.g., GPT-5.4 mini) to analyze emails and extract structured data."""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-5.4-mini"):
        """
        Initializes the AI Analyzer.
        
        Args:
            api_key (str, optional): OpenAI API key. Defaults to OPENAI_API_KEY environment variable.
            model (str): The OpenAI model to use. Default is 'gpt-5.4-mini'.
        """
        self.client = AsyncOpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.model = model

    async def analyze_email(self, subject: str, sender: str, body: str) -> Optional[EmailAnalysis]:
        """
        Analyzes the given email content and returns structured data.
        
        Args:
            subject (str): Email subject.
            sender (str): Email sender.
            body (str): Email body text.
            
        Returns:
            EmailAnalysis: Pydantic model with the extracted data, or None if failed.
        """
        prompt = f"""
        You are an intelligent email triage assistant.
        Please analyze the following email and extract the requested structured information.
        
        Sender: {sender}
        Subject: {subject}
        
        Body:
        {body}
        """

        try:
            # We use the beta.chat.completions.parse method for Pydantic structured outputs
            completion = await self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a professional AI assistant that extracts structured data from emails."},
                    {"role": "user", "content": prompt}
                ],
                response_format=EmailAnalysis,
            )
            
            result = completion.choices[0].message.parsed
            logger.info(f"Successfully analyzed email: {subject}")
            return result

        except Exception as e:
            logger.error(f"Failed to analyze email '{subject}': {e}")
            return None