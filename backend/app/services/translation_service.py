"""
Translation service using LiteLLM proxy (OpenAI-compatible API)

Provides auto-translation between English and Spanish for task template content.
Uses the platform's LiteLLM proxy with mistral-nemo model.
"""

import logging
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class TranslationService:
    """Translates text between English and Spanish using LiteLLM proxy"""

    @staticmethod
    async def translate(
        text: str,
        source_lang: str = "en",
        target_lang: str = "es",
    ) -> str:
        """
        Translate text from source_lang to target_lang via LiteLLM proxy.

        Args:
            text: The text to translate
            source_lang: Source language code ("en" or "es")
            target_lang: Target language code ("en" or "es")

        Returns:
            Translated text string

        Raises:
            ValueError: If LITELLM_API_KEY is not configured
            Exception: If LiteLLM API call fails
        """
        if not settings.LITELLM_API_KEY:
            raise ValueError("LITELLM_API_KEY is not configured")

        lang_names = {"en": "English", "es": "Spanish"}
        source_name = lang_names.get(source_lang, source_lang)
        target_name = lang_names.get(target_lang, target_lang)

        url = f"{settings.LITELLM_API_BASE}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.LITELLM_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.LITELLM_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"You are a translator. Translate the following text from {source_name} to {target_name}. "
                        "The text is a household task/chore title or description for a family task manager app. "
                        "Keep the translation natural and concise. Return ONLY the translated text, nothing else."
                    ),
                },
                {"role": "user", "content": text},
            ],
            "temperature": 0.3,
            "max_tokens": 500,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        translated = data["choices"][0]["message"]["content"]
        if not translated:
            raise Exception("LiteLLM returned empty translation")

        return translated.strip()

    @staticmethod
    async def translate_template_fields(
        title: str,
        description: str | None,
        source_lang: str = "en",
        target_lang: str = "es",
    ) -> dict:
        """
        Translate both title and description for a task template.

        Returns:
            Dict with 'title' and 'description' keys containing translated text
        """
        translated_title = await TranslationService.translate(
            title, source_lang, target_lang
        )

        translated_description = None
        if description:
            translated_description = await TranslationService.translate(
                description, source_lang, target_lang
            )

        return {
            "title": translated_title,
            "description": translated_description,
        }
