"""ElevenLabs text-to-speech provider.

The voice was chosen from the account's own voice list (``GET /v1/voices``,
verified 2026-10-08) rather than invented:

``zH7TN9vEZAsEway9xWev`` — **Beth**, labels ``accent=british``, ``gender=female``,
``age=young``. That is the young adult British female voice the brief asks for,
and the only entry in the list carrying all three labels. Other British female
voices on the account (``pFZP5JQG7iQjIQuC4Bku`` Lily) are labelled
``middle_aged``.

Failure is always graceful: :meth:`synthesize` raises
:class:`~app.providers.base.ProviderError`, the API returns 503 with an
explanation, and the UI keeps working without audio.
"""

from __future__ import annotations

import asyncio

import httpx

from app.config import Settings, get_settings, load_secrets
from app.providers.base import ProviderError, ProviderUnavailable, VoiceProvider

_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

#: Voice settings tuned for spoken troubleshooting guidance: steady, unhurried
#: and close to the source recording.
VOICE_SETTINGS = {
    "stability": 0.55,
    "similarity_boost": 0.75,
    "style": 0.10,
    "use_speaker_boost": True,
}


class ElevenLabsVoiceProvider(VoiceProvider):
    name = "elevenlabs"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._api_key = load_secrets().get("ELEVENLABS_API_KEY", "")

    async def is_available(self) -> bool:
        return bool(self._api_key)

    @property
    def default_voice_id(self) -> str:
        return self.settings.elevenlabs_voice_id

    async def synthesize(self, text: str, *, voice_id: str | None = None) -> tuple[bytes, str]:
        if not self._api_key:
            raise ProviderUnavailable(
                self.name,
                "ELEVENLABS_API_KEY is not configured; voice guidance is unavailable",
            )
        text = text.strip()
        if not text:
            raise ProviderError(self.name, "nothing to synthesize")

        voice = voice_id or self.default_voice_id
        url = f"{self.settings.elevenlabs_base_url.rstrip('/')}/text-to-speech/{voice}"
        payload = {
            "text": text,
            "model_id": self.settings.elevenlabs_model_id,
            "voice_settings": VOICE_SETTINGS,
        }
        headers = {"xi-api-key": self._api_key, "Content-Type": "application/json"}

        last_error: str | None = None
        attempts = self.settings.provider_max_retries + 1
        async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
            for attempt in range(attempts):
                try:
                    response = await client.post(url, headers=headers, json=payload)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                else:
                    if response.status_code < 400:
                        return response.content, response.headers.get(
                            "content-type", "audio/mpeg"
                        )
                    last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                    if response.status_code not in _RETRYABLE_STATUS:
                        raise ProviderError(self.name, last_error, status=response.status_code)

                if attempt < attempts - 1:
                    await asyncio.sleep(0.5 * (2**attempt))

        raise ProviderError(self.name, last_error or "speech synthesis failed after retries")


async def list_voices(settings: Settings | None = None) -> list[dict[str, object]]:
    """Return the account's voices with the labels used to pick the default."""
    settings = settings or get_settings()
    api_key = load_secrets().get("ELEVENLABS_API_KEY", "")
    if not api_key:
        raise ProviderUnavailable("elevenlabs", "ELEVENLABS_API_KEY is not configured")
    url = f"{settings.elevenlabs_base_url.rstrip('/')}/voices"
    async with httpx.AsyncClient(timeout=settings.provider_timeout_seconds) as client:
        response = await client.get(url, headers={"xi-api-key": api_key})
        response.raise_for_status()
        payload = response.json()
    out: list[dict[str, object]] = []
    for voice in payload.get("voices", []):
        labels = voice.get("labels") or {}
        out.append(
            {
                "voice_id": voice.get("voice_id"),
                "name": voice.get("name"),
                "accent": labels.get("accent"),
                "gender": labels.get("gender"),
                "age": labels.get("age"),
            }
        )
    return out
