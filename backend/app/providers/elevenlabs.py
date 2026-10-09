"""ElevenLabs text-to-speech provider.

Both voices named here were chosen from the account's own voice list
(``GET /v1/voices``) rather than invented, and the difference between them was
measured, not assumed:

* ``zH7TN9vEZAsEway9xWev`` — **Beth**, labelled ``accent=british``,
  ``gender=female``, ``age=young``. She is the young adult British female voice
the brief asks for, and the only entry in the list carrying all three labels.
  She is also a **library** voice, and the ElevenLabs API refuses library voices
  on the free plan: ``POST /v1/text-to-speech/<id>`` answers
  ``HTTP 402 {"code": "paid_plan_required"}``. Verified 2026-10-09 against both
  keys on this account.
* ``Xb7hH8MSUJpSbSDYk0k2`` — **Alice**, labelled ``accent=british``,
  ``gender=female``, ``age=middle_aged``. A **premade** voice, so every plan is
  allowed to speak with it. Verified returning ``200 audio/mpeg``.

:data:`PREMIUM_FALLBACK_VOICE_ID` is Alice. When the configured voice is refused
because the plan does not permit it, :meth:`synthesize` retries once with her and
reports the substitution on the returned
:class:`~app.providers.base.Speech` — a person standing in front of a broken
machine gets audio in the second British female voice rather than an error
message about a subscription. Any other failure still raises
:class:`~app.providers.base.ProviderError`, the API answers 502 with an
explanation, and the written guidance is unaffected.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import Settings, get_settings, load_secrets
from app.providers.base import ProviderError, ProviderUnavailable, Speech, VoiceProvider

logger = logging.getLogger("sightops.providers.elevenlabs")

_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

#: A premade voice every plan may use. See the module docstring.
PREMIUM_FALLBACK_VOICE_ID = "Xb7hH8MSUJpSbSDYk0k2"


def is_voice_refusal(status: int, body: str) -> bool:
    """True when the failure is this *voice* being unavailable to the account.

    A ``402`` is how ElevenLabs answers a library voice on the free plan
    (``paid_plan_required``). ``voice_not_found`` on a 400 or 404 means the id
    does not belong to this account, which is a configuration mistake with the
    same fix. Both are answered by speaking with a premade voice; a 429 or a 5xx
    is transient and must keep retrying on the voice that was asked for.
    """
    if status == 402:
        return True
    if status in {400, 404}:
        return "voice_not_found" in body
    return False


class _VoiceRefused(Exception):
    """Internal: the account may not use the requested voice."""

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

    async def synthesize(self, text: str, *, voice_id: str | None = None) -> Speech:
        if not self._api_key:
            raise ProviderUnavailable(
                self.name,
                "ELEVENLABS_API_KEY is not configured; voice guidance is unavailable",
            )
        text = text.strip()
        if not text:
            raise ProviderError(self.name, "nothing to synthesize")

        requested = voice_id or self.default_voice_id
        actual = requested
        async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
            try:
                audio, content_type = await self._post_speech(client, requested, text)
            except _VoiceRefused as exc:
                if requested == PREMIUM_FALLBACK_VOICE_ID:
                    # The fallback is a premade voice; if it too is refused there
                    # is no voice left to try and the caller should hear why.
                    raise ProviderError(self.name, str(exc)) from exc
                logger.warning(
                    "voice %s is unavailable to this account (%s); speaking with %s instead",
                    requested,
                    exc,
                    PREMIUM_FALLBACK_VOICE_ID,
                )
                actual = PREMIUM_FALLBACK_VOICE_ID
                try:
                    audio, content_type = await self._post_speech(client, actual, text)
                except _VoiceRefused as second:
                    raise ProviderError(self.name, str(second)) from second

        return Speech(
            audio=audio,
            content_type=content_type,
            voice_id=actual,
            requested_voice_id=requested,
        )

    async def _post_speech(self, client: httpx.AsyncClient, voice: str, text: str) -> tuple[bytes, str]:
        """POST one utterance to ``voice``, retrying only what is retryable.

        Raises :class:`_VoiceRefused` when the account is not allowed to use this
        voice at all, which is the one condition :meth:`synthesize` answers by
        changing voice rather than by giving up.
        """
        url = f"{self.settings.elevenlabs_base_url.rstrip('/')}/text-to-speech/{voice}"
        payload = {
            "text": text,
            "model_id": self.settings.elevenlabs_model_id,
            "voice_settings": VOICE_SETTINGS,
        }
        headers = {"xi-api-key": self._api_key, "Content-Type": "application/json"}

        last_error: str | None = None
        attempts = self.settings.provider_max_retries + 1
        for attempt in range(attempts):
            try:
                response = await client.post(url, headers=headers, json=payload)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code < 400:
                    return response.content, response.headers.get("content-type", "audio/mpeg")
                last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                if is_voice_refusal(response.status_code, response.text):
                    raise _VoiceRefused(f"HTTP {response.status_code}: {response.text[:300]}")
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
