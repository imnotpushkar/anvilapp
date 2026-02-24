"""
services/ai_service.py
──────────────────────
All communication with the Groq LLM lives here.
Routes never import groq_client directly — they always go through AIService.
"""

from config import groq_client, GROQ_MODEL


class AIService:
    """Thin wrapper around the Groq client."""

    @staticmethod
    def ask(prompt: str) -> str:
        """Send a single-turn prompt and return the text response."""
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content

    @staticmethod
    def ask_with_system(system: str, prompt: str) -> str:
        """Send a prompt with an explicit system message."""
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ]
        )
        return response.choices[0].message.content
