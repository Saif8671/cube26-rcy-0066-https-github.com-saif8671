"""Anthropic API client wrapper for Phase 5 AI Reasoning."""

from typing import Optional
from anthropic import (
    Anthropic,
    APIConnectionError,
    APIStatusError,
    RateLimitError,
    APITimeoutError,
)
import httpx
from app.core.config import settings
from app.core.logging import logger
from app.ai.exceptions import AIConfigurationError, AIProviderError


class AnthropicClient:
    """Isolated wrapper around Anthropic SDK with credential safety and sanitized error handling."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self._api_key = api_key if api_key is not None else settings.anthropic_api_key
        self.model = model or getattr(settings, "anthropic_model", "claude-3-5-sonnet-20241022")
        self._client: Optional[Anthropic] = None

    @property
    def client(self) -> Anthropic:
        """Lazily initialize Anthropic client, verifying API key presence."""
        if not self._api_key or not self._api_key.strip():
            raise AIConfigurationError("ANTHROPIC_API_KEY is not configured.")
        if self._client is None:
            self._client = Anthropic(api_key=self._api_key, http_client=httpx.Client())
        return self._client

    def generate_assessment(self, system_prompt: str, user_prompt: str) -> str:
        """
        Call Anthropic API to generate reasoning output.
        Returns the raw model text response.
        Ensures credentials are never logged or exposed.
        """
        try:
            anthropic_client = self.client
            message = anthropic_client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
            )
            text_blocks = [
                block.text for block in message.content if hasattr(block, "text")
            ]
            if not text_blocks:
                raise AIProviderError("AI provider returned an empty response.")
            return "".join(text_blocks)
        except AIConfigurationError:
            raise
        except (APIConnectionError, APITimeoutError) as exc:
            logger.error(f"Anthropic connection failure: {exc.__class__.__name__}")
            raise AIProviderError("AI reasoning provider connection error.") from exc
        except RateLimitError as exc:
            logger.error(f"Anthropic rate limit exceeded: {exc.__class__.__name__}")
            raise AIProviderError("AI reasoning provider rate limit exceeded.") from exc
        except APIStatusError as exc:
            logger.error(f"Anthropic API status error: status_code={exc.status_code}")
            raise AIProviderError("AI reasoning provider returned an error status.") from exc
        except Exception as exc:
            logger.error(f"Anthropic unexpected error: {exc.__class__.__name__}")
            raise AIProviderError("AI reasoning provider encountered an unexpected failure.") from exc
