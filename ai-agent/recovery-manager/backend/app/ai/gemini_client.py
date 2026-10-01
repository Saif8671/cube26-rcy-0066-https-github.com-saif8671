"""Google Gemini API client wrapper for Phase 5b AI Reasoning."""

import time
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field

from google import genai
from google.genai import types
from google.genai.errors import APIError, ServerError, ClientError

from app.core.config import settings
from app.core.logging import logger
from app.ai.exceptions import AIConfigurationError, AIProviderError


class AssessmentTypeEnum(str, Enum):
    """Assessment classification enum for structured schema generation."""
    CONTRADICTED = "CONTRADICTED"
    SUPPORTED = "SUPPORTED"
    SILENT = "SILENT"
    UNCERTAIN = "UNCERTAIN"


class GeminiAssessmentStructuredOutput(BaseModel):
    """
    Direct Pydantic schema bound to Gemini's response_schema.
    Ensures clean schema generation without conflicting meta-attributes.
    """
    assessment: AssessmentTypeEnum = Field(
        description="Assessment classification: CONTRADICTED, SUPPORTED, SILENT, UNCERTAIN"
    )
    claim_supported: bool = Field(
        description="Whether a recovery claim is supported by evidence"
    )
    claim_amount: Optional[float] = Field(
        default=None,
        description="Recommended claim amount if recovery supported"
    )
    confidence: float = Field(
        description="Confidence score between 0.0 and 1.0"
    )
    reason: str = Field(
        description="Detailed reasoning explaining the assessment"
    )
    evidence_ids: List[str] = Field(
        default_factory=list,
        description="IDs of evidence supporting this assessment"
    )


class GeminiClient:
    """
    Isolated wrapper around Google GenAI SDK with credential safety and sanitized error handling.
    Exposes the exact same public method signature and return contract as AnthropicClient:
        generate_assessment(system_prompt: str, user_prompt: str) -> str
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_retries: int = 3,
        retry_delay_seconds: float = 2.0,
    ):
        self._api_key = api_key if api_key is not None else settings.gemini_api_key
        # Default model is configured via settings (gemini-flash-latest / Gemini 3.8 Flash)
        self.model = model or getattr(settings, "gemini_model", "gemini-flash-latest")
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self._client: Optional[genai.Client] = None

    @property
    def client(self) -> genai.Client:
        """Lazily initialize Gemini Client, verifying API key presence."""
        if not self._api_key or not self._api_key.strip():
            raise AIConfigurationError("GEMINI_API_KEY is not configured.")
        if self._client is None:
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def generate_assessment(self, system_prompt: str, user_prompt: str) -> str:
        """
        Call Gemini API to generate reasoning output using native structured output.
        Returns the raw model text response (a valid JSON string).
        Ensures credentials are never logged or exposed.
        Includes automated retry logic for transient 503 high-demand spikes.
        """
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                gemini_client = self.client
                response = gemini_client.models.generate_content(
                    model=self.model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        response_mime_type="application/json",
                        response_schema=GeminiAssessmentStructuredOutput,
                        temperature=0.0,
                    ),
                )
                if not response.text or not response.text.strip():
                    raise AIProviderError("AI provider returned an empty response.")
                return response.text.strip()
            except AIConfigurationError:
                raise
            except ServerError as exc:
                last_error = exc
                logger.warning(
                    f"Gemini ServerError (503/unavailable) on attempt {attempt + 1}: {exc.__class__.__name__}"
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay_seconds * (attempt + 1))
                    continue
                logger.error(f"Gemini server error exhausted retries: {exc.__class__.__name__}")
                raise AIProviderError("AI reasoning provider server error or high demand.") from exc
            except ClientError as exc:
                logger.error(f"Gemini client/API status error: status_code={getattr(exc, 'code', 'unknown')}")
                raise AIProviderError("AI reasoning provider returned a client error status.") from exc
            except APIError as exc:
                logger.error(f"Gemini API failure: {exc.__class__.__name__}")
                raise AIProviderError("AI reasoning provider connection error.") from exc
            except Exception as exc:
                logger.error(f"Gemini unexpected error: {exc.__class__.__name__}")
                raise AIProviderError("AI reasoning provider encountered an unexpected failure.") from exc

        raise AIProviderError("AI reasoning provider call failed after retries.") from last_error
