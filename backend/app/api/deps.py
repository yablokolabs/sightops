"""Shared application context for the API layer.

One ``AppContext`` lives on ``app.state`` and is created during startup. Routers
pull it through :func:`get_context`, so nothing constructs its own repository or
provider per request.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.agent.loop import InspectionAgent
from app.config import Settings, get_settings
from app.providers.base import ModelProvider
from app.providers.elevenlabs import ElevenLabsVoiceProvider
from app.providers.nebius import NebiusProvider
from app.storage.evidence import LocalEvidenceStorage
from app.storage.repo import Repository
from app.vision.engine import VisionEngine


@dataclass
class AppContext:
    settings: Settings
    repo: Repository
    engine: VisionEngine
    evidence: LocalEvidenceStorage
    agent: InspectionAgent
    model_provider: ModelProvider
    voice_provider: ElevenLabsVoiceProvider

    async def aclose(self) -> None:
        await self.repo.close()


def get_context(request: Request) -> AppContext:
    context = getattr(request.app.state, "context", None)
    if context is None:  # pragma: no cover - only before startup completes
        raise RuntimeError("application context is not initialised")
    return context


async def build_context(settings: Settings | None = None) -> AppContext:
    settings = settings or get_settings()
    repo = await Repository.open(settings.db_path)
    engine = VisionEngine(settings)
    provider = NebiusProvider(settings)
    agent = InspectionAgent(repo, engine, provider, settings)
    return AppContext(
        settings=settings,
        repo=repo,
        engine=engine,
        evidence=LocalEvidenceStorage(settings.evidence_dir),
        agent=agent,
        model_provider=provider,
        voice_provider=ElevenLabsVoiceProvider(settings),
    )
