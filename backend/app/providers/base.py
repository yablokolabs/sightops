"""Provider abstractions.

The agent talks to :class:`ModelProvider` and :class:`VoiceProvider`, never to a
vendor SDK. This is what keeps the Amazon Bedrock adapter described in
``docs/architecture/aws.md`` a drop-in rather than a rewrite, and it is also
what lets the deterministic demonstration policy run the same tool loop without
a network call.

All provider calls originate server-side. No API key ever reaches the browser.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ModelResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    usage: Usage = field(default_factory=Usage)
    finish_reason: str | None = None
    #: True when the provider could not be reached and this is a degraded reply.
    degraded: bool = False
    error: str | None = None


class ProviderError(RuntimeError):
    """Raised when a provider call fails after retries."""

    def __init__(self, provider: str, message: str, *, status: int | None = None) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.status = status


@dataclass
class Speech:
    """One synthesized piece of guidance, with the voice that actually spoke it.

    ``voice_id`` is the voice that produced ``audio``, which is not always the
    voice that was asked for: a plan that refuses a library voice is answered
    with a premade one rather than with an error. ``substituted`` is true
    exactly when that happened, so the caller can say so instead of quietly
    presenting a different voice as the configured one.
    """

    audio: bytes
    content_type: str = "audio/mpeg"
    voice_id: str = ""
    requested_voice_id: str = ""

    @property
    def substituted(self) -> bool:
        return bool(self.requested_voice_id) and self.voice_id != self.requested_voice_id


class ProviderUnavailable(ProviderError):
    """Raised when the provider is not configured (for example, no API key)."""


class ModelProvider(ABC):
    """A chat-completion backend with optional tool calling."""

    name: str = "model"

    @abstractmethod
    async def is_available(self) -> bool: ...

    @abstractmethod
    async def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1200,
        temperature: float = 0.2,
    ) -> ModelResponse: ...

    @abstractmethod
    async def describe_image(
        self, prompt: str, image_bytes: bytes, *, mime: str = "image/png", max_tokens: int = 600
    ) -> str:
        """Ask a vision-language model to describe an image in text.

        The answer is always tagged :class:`~app.models.schemas.Provenance.INFERRED`;
        it must never overwrite a value OpenCV measured.
        """


class VoiceProvider(ABC):
    """A text-to-speech backend."""

    name: str = "voice"

    @abstractmethod
    async def is_available(self) -> bool: ...

    @abstractmethod
    async def synthesize(self, text: str, *, voice_id: str | None = None) -> Speech:
        """Return the synthesized audio together with the voice that produced it.

        ``voice_id`` overrides the configured voice for this one call. Providers
        are expected to substitute a voice they are allowed to use rather than
        fail, and to report that substitution on the returned
        :class:`Speech`.
        """
