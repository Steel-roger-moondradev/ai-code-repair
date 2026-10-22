"""Application-owned, lazy Groq LLM adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.config import Settings, get_settings


class LLMConfigurationError(RuntimeError):
    """Raised when the provider cannot be used because configuration is missing."""


class LLMProviderError(RuntimeError):
    """Raised when the provider fails without producing usable output."""


@dataclass(frozen=True)
class LLMResponse:
    """Provider output and optional usage metadata."""

    text: str
    usage: dict[str, Any]


class GroqLLMAdapter:
    """Small async adapter with lazy client creation and bounded retries."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client_factory: Callable[[str], Any] | None = None,
        max_retries: int = 1,
    ) -> None:
        self.settings = settings or get_settings()
        self._client_factory = client_factory
        self._client: Any | None = None
        self.max_retries = max(0, max_retries)

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> LLMResponse:
        """Return bounded provider output without making calls during import."""

        if not self.settings.groq_api_key:
            raise LLMConfigurationError("GROQ_API_KEY is not configured")
        if not self.settings.groq_model:
            raise LLMConfigurationError("GROQ_MODEL is not configured")
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")

        client = self._get_client()
        request = {
            "model": self.settings.groq_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "max_tokens": max_output_tokens,
        }
        for attempt in range(self.max_retries + 1):
            try:
                response = await asyncio.wait_for(
                    client.chat.completions.create(**request),
                    timeout=self.settings.llm_timeout_seconds,
                )
                choice = response.choices[0]
                text = choice.message.content
                if not isinstance(text, str) or not text.strip():
                    raise LLMProviderError("Groq returned empty output")
                usage = getattr(response, "usage", None)
                return LLMResponse(
                    text=text,
                    usage=usage.model_dump() if hasattr(usage, "model_dump") else {},
                )
            except LLMProviderError:
                raise
            except Exception as exc:
                if attempt < self.max_retries and _is_transient_provider_error(exc):
                    await asyncio.sleep(0.05 * (attempt + 1))
                    continue
                raise LLMProviderError("Groq request failed") from exc
        raise LLMProviderError("Groq request failed")

    def _get_client(self) -> Any:
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory(self.settings.groq_api_key or "")
            else:
                from groq import AsyncGroq

                self._client = AsyncGroq(
                    api_key=self.settings.groq_api_key,
                    timeout=self.settings.llm_timeout_seconds,
                )
        return self._client


def _is_transient_provider_error(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    return status_code == 408 or status_code == 429 or (
        isinstance(status_code, int) and status_code >= 500
    )
