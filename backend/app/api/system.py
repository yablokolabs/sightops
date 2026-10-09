"""Health, system status, incidents and voice routes."""

from __future__ import annotations

import platform

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.api.deps import AppContext, get_context
from app.config import load_secrets
from app.models.schemas import HealthResponse, Incident, SystemStatus, VoiceRequest
from app.providers.base import ProviderError, ProviderUnavailable
from app.vision.engine import opencv_version, version_report
from app.vision.profiles import list_profiles

health_router = APIRouter(tags=["system"])
system_router = APIRouter(prefix="/api/system", tags=["system"])
incident_router = APIRouter(prefix="/api/incidents", tags=["incidents"])
voice_router = APIRouter(prefix="/api/voice", tags=["voice"])


@health_router.get("/health", response_model=HealthResponse)
async def health(context: AppContext = Depends(get_context)) -> HealthResponse:
    database = True
    try:
        await context.repo.list_inspections(limit=1)
    except Exception:  # noqa: BLE001 - health must not raise
        database = False
    return HealthResponse(
        status="ok" if database else "degraded",
        database=database,
        opencv_version=opencv_version(),
    )


@system_router.get("/status", response_model=SystemStatus)
async def status(context: AppContext = Depends(get_context)) -> SystemStatus:
    """Report configuration *presence* only. No secret value is ever returned."""
    report = version_report()
    return SystemStatus(
        opencv_version=str(report["opencv_version"]),
        python_version=platform.python_version(),
        providers=context.settings.provider_status(),
        nebius_model=context.settings.nebius_model,
        nebius_vision_model=context.settings.nebius_vision_model,
        elevenlabs_voice_id=context.settings.elevenlabs_voice_id,
        demo_mode_default=context.settings.demo_mode,
        aws_integration="NOT IMPLEMENTED",
        profiles=list_profiles(),
    )


@system_router.get("/opencv")
async def opencv_status() -> dict:
    """Explicitly report whether the running OpenCV really is version 5."""
    report = version_report()
    return {
        **report,
        "claim": (
            "SightOps requires OpenCV 5 and this build runs on it."
            if report["is_opencv_5"]
            else "SightOps requires OpenCV 5 but this build is running an older major version."
        ),
    }


@incident_router.get("", response_model=list[Incident])
async def list_incidents(
    limit: int = Query(default=100, ge=1, le=500), context: AppContext = Depends(get_context)
) -> list[Incident]:
    return await context.repo.list_incidents(limit=limit)


@incident_router.get("/{incident_id}", response_model=Incident)
async def get_incident(incident_id: str, context: AppContext = Depends(get_context)) -> Incident:
    incident = await context.repo.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"no incident with id {incident_id}")
    return incident


@voice_router.get("/status")
async def voice_status(context: AppContext = Depends(get_context)) -> dict:
    configured = bool(load_secrets().get("ELEVENLABS_API_KEY"))
    return {
        "provider": "elevenlabs",
        "configured": configured,
        "voice_id": context.settings.elevenlabs_voice_id,
        "model_id": context.settings.elevenlabs_model_id,
        "message": (
            "Voice guidance is available."
            if configured
            else "ELEVENLABS_API_KEY is not configured, so voice guidance is unavailable. "
            "All written guidance still works."
        ),
    }


@voice_router.post("/synthesize")
async def synthesize(
    payload: VoiceRequest, context: AppContext = Depends(get_context)
) -> Response:
    try:
        speech = await context.voice_provider.synthesize(
            payload.text, voice_id=payload.voice_id
        )
    except ProviderUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=f"{exc}. Written guidance is unaffected.",
        ) from exc
    except ProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Speech synthesis failed: {exc}. Written guidance is unaffected.",
        ) from exc

    # A plan that refuses the configured voice is answered by speaking with a
    # premade one. The headers say which voice actually spoke, so a substitution
    # is visible to the client instead of being presented as the configured one.
    headers = {
        "X-SightOps-Voice-Id": speech.voice_id,
        "X-SightOps-Voice-Requested": speech.requested_voice_id,
        "X-SightOps-Voice-Substituted": "true" if speech.substituted else "false",
    }
    return Response(content=speech.audio, media_type=speech.content_type, headers=headers)
