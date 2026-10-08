"""Nebius AI Studio provider.

Nebius exposes an OpenAI-compatible ``/chat/completions`` endpoint, so this is a
thin, carefully-bounded HTTP client rather than an SDK wrapper. Verified against
``https://api.studio.nebius.com/v1`` on 2026-10-08:

* ``GET /models`` returns the served model list (used by
  ``scripts/check_providers.py``).
* Tool calling works for ``Qwen/Qwen3.5-397B-A17B``, ``zai-org/GLM-5.3``,
  ``deepseek-ai/DeepSeek-V4-Pro`` and ``moonshotai/Kimi-K3``: each returned a
  well-formed ``tool_calls`` array with ``finish_reason="tool_calls"``.
* ``openbmb/MiniCPM-V-4_5`` is served for multimodal interpretation.

Every call is timeout-bounded and retried on transport errors, 429 and 5xx with
exponential backoff. A failure raises :class:`ProviderError`; the agent turns
that into an observable degraded step rather than a silent fallback.
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

import httpx

from app.config import Settings, get_settings, load_secrets
from app.providers.base import (
    ModelProvider,
    ModelResponse,
    ProviderError,
    ProviderUnavailable,
    ToolCall,
    Usage,
)

_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class NebiusProvider(ModelProvider):
    name = "nebius"

    def __init__(self, settings: Settings | None = None, *, model: str | None = None) -> None:
        self.settings = settings or get_settings()
        self.model = model or self.settings.nebius_model
        self._api_key = load_secrets().get("NEBIUS_API_KEY", "")

    async def is_available(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._api_key:
            raise ProviderUnavailable(
                self.name, "NEBIUS_API_KEY is not configured; set it in ~/.hermes/.env or the environment"
            )

        url = f"{self.settings.nebius_base_url.rstrip('/')}{path}"
        last_error: str | None = None
        attempts = self.settings.provider_max_retries + 1

        async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
            for attempt in range(attempts):
                try:
                    response = await client.post(url, headers=self._headers(), json=payload)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                else:
                    if response.status_code < 400:
                        return response.json()
                    last_error = f"HTTP {response.status_code}: {response.text[:400]}"
                    if response.status_code not in _RETRYABLE_STATUS:
                        raise ProviderError(self.name, last_error, status=response.status_code)

                if attempt < attempts - 1:
                    await asyncio.sleep(0.6 * (2**attempt))

        raise ProviderError(self.name, last_error or "request failed after retries")

    async def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1200,
        temperature: float = 0.2,
    ) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        data = await self._post("/chat/completions", payload)
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}

        calls: list[ToolCall] = []
        for index, raw in enumerate(message.get("tool_calls") or []):
            function = raw.get("function") or {}
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"_raw": arguments}
            calls.append(
                ToolCall(
                    id=raw.get("id") or f"call_{index}",
                    name=function.get("name") or "",
                    arguments=arguments if isinstance(arguments, dict) else {},
                )
            )

        raw_usage = data.get("usage") or {}
        return ModelResponse(
            content=message.get("content") or "",
            tool_calls=calls,
            model=data.get("model") or self.model,
            usage=Usage(
                prompt_tokens=raw_usage.get("prompt_tokens", 0),
                completion_tokens=raw_usage.get("completion_tokens", 0),
                total_tokens=raw_usage.get("total_tokens", 0),
            ),
            finish_reason=choice.get("finish_reason"),
        )

    async def describe_image(
        self,
        prompt: str,
        image_bytes: bytes,
        *,
        mime: str = "image/png",
        max_tokens: int = 600,
    ) -> str:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "model": self.settings.nebius_vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                    ],
                }
            ],
            "max_tokens": max_tokens,
            "temperature": 0.1,
        }
        data = await self._post("/chat/completions", payload)
        choice = (data.get("choices") or [{}])[0]
        return ((choice.get("message") or {}).get("content") or "").strip()


async def list_models(settings: Settings | None = None) -> list[str]:
    """Return the served model ids, used by the provider check script."""
    settings = settings or get_settings()
    api_key = load_secrets().get("NEBIUS_API_KEY", "")
    if not api_key:
        raise ProviderUnavailable("nebius", "NEBIUS_API_KEY is not configured")
    url = f"{settings.nebius_base_url.rstrip('/')}/models"
    async with httpx.AsyncClient(timeout=settings.provider_timeout_seconds) as client:
        response = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
        response.raise_for_status()
        return sorted(entry["id"] for entry in response.json().get("data", []))
