"""ElevenLabs voice provider tests.

The provider is exercised against a stub HTTP transport rather than the network,
so these tests run offline. What they check is the decision the provider makes
when the account's plan refuses the configured voice: the real account, on the
free plan, answers ``HTTP 402 paid_plan_required`` for the library voice
``zH7TN9vEZAsEway9xWev``. Voice guidance has to survive that.
"""

from __future__ import annotations

from dataclasses import dataclass
from json import dumps as json_dumps

import pytest

from app.config import LIBRARY_VOICE_ID, Settings
from app.providers import elevenlabs
from app.providers.base import ProviderError, ProviderUnavailable
from app.providers.elevenlabs import (
    PREMIUM_FALLBACK_VOICE_ID,
    ElevenLabsVoiceProvider,
    is_voice_refusal,
)

AUDIO = b"\xff\xfb\x90\x00fake-mpeg-bytes"

PAID_PLAN_REQUIRED = {
    "detail": {
        "type": "payment_required",
        "code": "paid_plan_required",
        "message": "Free users cannot use library voices via the API.",
        "status": "payment_required",
    }
}


@dataclass
class _Response:
    status_code: int
    content: bytes
    content_type: str = "audio/mpeg"

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")

    @property
    def headers(self) -> dict[str, str]:
        return {"content-type": self.content_type}


class _Call(dict):
    @property
    def voice(self) -> str:
        return self["url"].rsplit("/", 1)[-1]


def _install_transport(monkeypatch, script: list[tuple[int, object]]):
    """Replace ``httpx.AsyncClient`` with a stub that replays ``script``.

    ``script`` is consumed one entry per POST; the last entry repeats. An int
    payload becomes an empty body, a dict becomes a JSON body, bytes are used
    as they are. Returns the list of calls the provider made.
    """
    calls: list[_Call] = []

    class _Client:
        def __init__(self, *args, **kwargs) -> None:  # noqa: D107 - stub
            pass

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *exc_info) -> bool:
            return False

        async def post(self, url, *, headers=None, json=None, **kwargs):
            calls.append(_Call(url=url, headers=headers or {}, json=json))
            index = min(len(calls) - 1, len(script) - 1)
            status, payload = script[index]
            if isinstance(payload, bytes):
                return _Response(status, payload)
            if isinstance(payload, dict):
                return _Response(
                    status, json_dumps(payload).encode(), content_type="application/json"
                )
            return _Response(status, b"")

    monkeypatch.setattr(elevenlabs.httpx, "AsyncClient", _Client)
    return calls


@pytest.fixture
def configured_settings(tmp_path):
    """Settings with a key, so ``load_secrets`` is not the thing under test."""

    class _Settings(Settings):
        pass

    return _Settings(data_dir=tmp_path, provider_max_retries=0)


def _provider(monkeypatch, settings, *, voice_id: str, api_key: str = "test-key"):
    monkeypatch.setattr(elevenlabs, "load_secrets", lambda: {"ELEVENLABS_API_KEY": api_key})
    settings.elevenlabs_voice_id = voice_id
    return ElevenLabsVoiceProvider(settings)


# --------------------------------------------------------------------------
# the pure predicate
# --------------------------------------------------------------------------


def test_a_402_is_a_voice_refusal():
    assert is_voice_refusal(402, json_dumps(PAID_PLAN_REQUIRED))


def test_a_missing_voice_id_is_a_voice_refusal():
    assert is_voice_refusal(404, '{"detail": {"status": "voice_not_found"}}')


@pytest.mark.parametrize("status", [429, 500, 503])
def test_a_transient_failure_is_not_a_voice_refusal(status):
    assert not is_voice_refusal(status, "upstream timeout")


def test_a_404_for_another_reason_is_not_a_voice_refusal():
    assert not is_voice_refusal(404, '{"detail": {"status": "model_not_found"}}')


# --------------------------------------------------------------------------
# the decision
# --------------------------------------------------------------------------


async def test_the_library_voice_falls_back_to_a_premade_one(monkeypatch, configured_settings):
    calls = _install_transport(
        monkeypatch,
        [(402, PAID_PLAN_REQUIRED), (200, AUDIO)],
    )
    provider = _provider(monkeypatch, configured_settings, voice_id=LIBRARY_VOICE_ID)

    speech = await provider.synthesize("Check that the machine is switched off.")

    assert [call.voice for call in calls] == [LIBRARY_VOICE_ID, PREMIUM_FALLBACK_VOICE_ID]
    assert speech.audio == AUDIO
    assert speech.content_type == "audio/mpeg"
    assert speech.voice_id == PREMIUM_FALLBACK_VOICE_ID
    assert speech.requested_voice_id == LIBRARY_VOICE_ID
    assert speech.substituted is True


async def test_a_working_voice_is_used_exactly_as_configured(monkeypatch, configured_settings):
    calls = _install_transport(monkeypatch, [(200, AUDIO)])
    provider = _provider(monkeypatch, configured_settings, voice_id=PREMIUM_FALLBACK_VOICE_ID)

    speech = await provider.synthesize("Switch the isolator off first.")

    assert [call.voice for call in calls] == [PREMIUM_FALLBACK_VOICE_ID]
    assert speech.voice_id == PREMIUM_FALLBACK_VOICE_ID
    assert speech.substituted is False
    assert speech.requested_voice_id == PREMIUM_FALLBACK_VOICE_ID


async def test_a_per_call_voice_id_overrides_the_configured_one(monkeypatch, configured_settings):
    calls = _install_transport(monkeypatch, [(200, AUDIO)])
    provider = _provider(monkeypatch, configured_settings, voice_id=PREMIUM_FALLBACK_VOICE_ID)

    speech = await provider.synthesize("Read the gauge once more.", voice_id=LIBRARY_VOICE_ID)

    assert [call.voice for call in calls] == [LIBRARY_VOICE_ID]
    assert speech.substituted is False
    assert speech.voice_id == LIBRARY_VOICE_ID


async def test_a_transient_failure_is_not_answered_by_changing_voice(monkeypatch, configured_settings):
    calls = _install_transport(monkeypatch, [(503, b"")])
    provider = _provider(monkeypatch, configured_settings, voice_id=LIBRARY_VOICE_ID)

    with pytest.raises(ProviderError) as caught:
        await provider.synthesize("Check the door seal.")

    assert [call.voice for call in calls] == [LIBRARY_VOICE_ID]
    assert "503" in str(caught.value)


async def test_a_refused_fallback_is_reported_rather_than_retried_forever(
    monkeypatch, configured_settings
):
    calls = _install_transport(monkeypatch, [(402, PAID_PLAN_REQUIRED)])
    provider = _provider(monkeypatch, configured_settings, voice_id=PREMIUM_FALLBACK_VOICE_ID)

    with pytest.raises(ProviderError) as caught:
        await provider.synthesize("Check the filter.")

    assert [call.voice for call in calls] == [PREMIUM_FALLBACK_VOICE_ID]
    assert "paid_plan_required" in str(caught.value)


async def test_no_key_is_unavailable_rather_than_an_error(monkeypatch, configured_settings):
    _install_transport(monkeypatch, [(200, AUDIO)])
    monkeypatch.setattr(elevenlabs, "load_secrets", lambda: {})
    provider = ElevenLabsVoiceProvider(configured_settings)

    assert await provider.is_available() is False
    with pytest.raises(ProviderUnavailable):
        await provider.synthesize("Check the machine.")


async def test_empty_text_is_rejected_before_any_request(monkeypatch, configured_settings):
    calls = _install_transport(monkeypatch, [(200, AUDIO)])
    provider = _provider(monkeypatch, configured_settings, voice_id=PREMIUM_FALLBACK_VOICE_ID)

    with pytest.raises(ProviderError):
        await provider.synthesize("   ")

    assert calls == []


async def test_the_api_key_never_appears_in_an_error(monkeypatch, configured_settings):
    secret = "sk_this_must_not_leak_0123456789"
    _install_transport(monkeypatch, [(418, {"detail": "teapot"})])
    provider = _provider(
        monkeypatch, configured_settings, voice_id=PREMIUM_FALLBACK_VOICE_ID, api_key=secret
    )

    with pytest.raises(ProviderError) as caught:
        await provider.synthesize("Check the machine.")

    assert secret not in str(caught.value)
