"""Inspection routes.

Thin by design: they validate input, delegate to the vision engine or the agent,
and return typed models. Business rules live in the agent and vision layers so
the HTTP surface cannot drift from what the tests exercise.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from app.api.deps import AppContext, get_context
from app.models.schemas import (
    ApprovalDecision,
    Incident,
    IncidentStatus,
    Inspection,
    InspectionCreate,
    InspectionState,
    MessageCreate,
    Observation,
    TimelineEntry,
    TimelineKind,
    ToolCallRecord,
    utcnow,
)
from app.storage.evidence import sha256_of
from app.vision.annotate import draw_analysis, encode_png
from app.vision.engine import ImageValidationError
from app.vision.profiles import resolve_profile

router = APIRouter(prefix="/api/inspections", tags=["inspections"])

_ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/bmp",
    "application/octet-stream",  # browsers sometimes send this for camera captures
}


async def _load(context: AppContext, inspection_id: str) -> Inspection:
    inspection = await context.repo.get_inspection(inspection_id)
    if inspection is None:
        raise HTTPException(status_code=404, detail=f"no inspection with id {inspection_id}")
    return inspection


@router.post("", response_model=Inspection, status_code=201)
async def create_inspection(
    payload: InspectionCreate, context: AppContext = Depends(get_context)
) -> Inspection:
    try:
        profile = resolve_profile(payload.mode, payload.profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    inspection = Inspection(
        id=uuid.uuid4().hex,
        mode=payload.mode,
        profile_id=profile.profile_id,
        problem_statement=payload.problem_statement,
        appliance=payload.appliance,
        demo_mode=payload.demo_mode if payload.demo_mode is not None else context.settings.demo_mode,
    )
    await context.repo.create_inspection(inspection)
    await context.repo.add_timeline(
        inspection.id,
        TimelineKind.REASONING,
        "Inspection created",
        (
            f"{profile.label}. {profile.description} "
            + ("Running in DEMO MODE (deterministic policy)." if inspection.demo_mode else "Running in LIVE AI mode.")
        ),
        state=InspectionState.CREATED,
        data={"profile_id": profile.profile_id, "mode": inspection.mode.value},
    )
    return await _load(context, inspection.id)


@router.get("", response_model=list[Inspection])
async def list_inspections(
    limit: int = Query(default=50, ge=1, le=200), context: AppContext = Depends(get_context)
) -> list[Inspection]:
    return await context.repo.list_inspections(limit=limit)


@router.get("/{inspection_id}", response_model=Inspection)
async def get_inspection(inspection_id: str, context: AppContext = Depends(get_context)) -> Inspection:
    return await _load(context, inspection_id)


@router.post("/{inspection_id}/images", response_model=Inspection, status_code=201)
async def upload_image(
    inspection_id: str,
    file: UploadFile = File(...),
    run_agent: bool = Form(default=True),
    context: AppContext = Depends(get_context),
) -> Inspection:
    inspection = await _load(context, inspection_id)

    content_type = (file.content_type or "").lower()
    if content_type and content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"unsupported content type {content_type!r}; send a JPEG, PNG or WebP image",
        )

    data = await file.read()
    try:
        image = context.engine.decode(data)
    except ImageValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    image_id = uuid.uuid4().hex
    height, width = image.shape[:2]
    key = context.evidence.put(inspection_id, image_id, "img", data)
    sequence = await context.repo.next_sequence(inspection_id)

    await context.repo.add_image(
        image_id=image_id,
        inspection_id=inspection_id,
        original_name=file.filename,
        content_type=content_type or "application/octet-stream",
        sha256=sha256_of(data),
        width=width,
        height=height,
        stored_path=key,
        role="primary" if sequence == 1 else "follow_up",
        sequence=sequence,
        created_at=utcnow().isoformat(),
    )
    await context.repo.add_observation(
        uuid.uuid4().hex, inspection_id, image_id, None, utcnow().isoformat()
    )
    await context.repo.add_timeline(
        inspection_id,
        TimelineKind.OBSERVATION,
        f"Observation {sequence} received",
        f"{file.filename or 'upload'} — {width}x{height} px, {len(data) / 1024:.0f} KiB",
        state=inspection.state,
        data={"image_id": image_id, "sequence": sequence},
    )

    # A fresh image answers any outstanding request for a better view.
    if inspection.pending_request is not None:
        inspection.pending_request = None
        await context.repo.update_inspection(inspection)

    if run_agent:
        await context.agent.run(inspection_id, user_message=None)
    return await _load(context, inspection_id)


@router.post("/{inspection_id}/analyze", response_model=Inspection)
async def analyze(
    inspection_id: str,
    image_id: str | None = Query(default=None),
    context: AppContext = Depends(get_context),
) -> Inspection:
    """Run the agent loop over the images attached to this inspection."""
    await _load(context, inspection_id)
    await context.agent.run(inspection_id)
    return await _load(context, inspection_id)


@router.post("/{inspection_id}/messages", response_model=Inspection)
async def post_message(
    inspection_id: str, payload: MessageCreate, context: AppContext = Depends(get_context)
) -> Inspection:
    await _load(context, inspection_id)
    if payload.run_agent:
        await context.agent.run(inspection_id, user_message=payload.content)
    else:
        await context.repo.add_timeline(
            inspection_id, TimelineKind.USER_MESSAGE, "User message", payload.content
        )
    return await _load(context, inspection_id)


@router.get("/{inspection_id}/observations", response_model=list[Observation])
async def list_observations(
    inspection_id: str, context: AppContext = Depends(get_context)
) -> list[Observation]:
    await _load(context, inspection_id)
    return await context.repo.list_observations(inspection_id)


@router.get("/{inspection_id}/timeline", response_model=list[TimelineEntry])
async def get_timeline(
    inspection_id: str, context: AppContext = Depends(get_context)
) -> list[TimelineEntry]:
    await _load(context, inspection_id)
    return await context.repo.list_timeline(inspection_id)


@router.get("/{inspection_id}/tool-calls", response_model=list[ToolCallRecord])
async def get_tool_calls(
    inspection_id: str, context: AppContext = Depends(get_context)
) -> list[ToolCallRecord]:
    await _load(context, inspection_id)
    return await context.repo.list_tool_calls(inspection_id)


@router.get("/{inspection_id}/evidence/{image_id}")
async def get_evidence(
    inspection_id: str,
    image_id: str,
    annotated: bool = Query(default=False),
    context: AppContext = Depends(get_context),
) -> Response:
    await _load(context, inspection_id)
    record = await context.repo.get_image(image_id)
    if record is None or record["inspection_id"] != inspection_id:
        raise HTTPException(status_code=404, detail=f"no image {image_id} in this inspection")

    key = record["annotated_path"] if annotated else record["stored_path"]
    if annotated and not key:
        # Annotate on demand if the agent loop has not produced one yet.
        observations = await context.repo.list_observations(inspection_id)
        analysis = next(
            (o.analysis for o in observations if o.image_id == image_id and o.analysis), None
        )
        if analysis is None:
            raise HTTPException(
                status_code=409, detail="this image has not been analysed yet, so it has no annotations"
            )
        try:
            raw = context.evidence.get(record["stored_path"])
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=410, detail="the stored evidence is unavailable") from exc
        annotated_image = draw_analysis(context.engine.decode(raw), analysis)
        payload = encode_png(annotated_image)
        key = context.evidence.put(inspection_id, f"{image_id}-annotated", "png", payload)
        await context.repo.set_annotated_path(image_id, key)
        return Response(content=payload, media_type="image/png")

    try:
        payload = context.evidence.get(key)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=410, detail="the stored evidence is unavailable") from exc
    return Response(content=payload, media_type="image/png" if annotated else record["content_type"])


@router.post("/{inspection_id}/approve", response_model=Incident)
async def approve(
    inspection_id: str,
    decision: ApprovalDecision,
    context: AppContext = Depends(get_context),
) -> Incident:
    return await _decide(context, inspection_id, approved=True, note=decision.note)


@router.post("/{inspection_id}/reject", response_model=Incident)
async def reject(
    inspection_id: str,
    decision: ApprovalDecision,
    context: AppContext = Depends(get_context),
) -> Incident:
    return await _decide(context, inspection_id, approved=False, note=decision.note)


async def _decide(context: AppContext, inspection_id: str, *, approved: bool, note: str) -> Incident:
    inspection = await _load(context, inspection_id)
    if inspection.incident_id is None:
        raise HTTPException(
            status_code=409,
            detail="this inspection has no incident awaiting approval",
        )
    incident = await context.repo.get_incident(inspection.incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="the incident record is missing")

    incident.status = (
        IncidentStatus.REMEDIATION_APPROVED if approved else IncidentStatus.REMEDIATION_REJECTED
    )
    incident.resolution_note = note or (
        "Reviewed and approved by a human operator." if approved else "Reviewed and rejected by a human operator."
    )
    incident.updated_at = utcnow()
    await context.repo.update_incident(incident)

    inspection.state = InspectionState.COMPLETED
    inspection.outcome = (
        "Simulated remediation approved by a human operator. Nothing was executed on real "
        "equipment; this demonstrator is a mock panel."
        if approved
        else "Simulated remediation rejected by a human operator. No action was taken."
    )
    inspection.resolved = approved
    inspection.updated_at = utcnow()
    await context.repo.update_inspection(inspection)

    await context.repo.add_timeline(
        inspection_id,
        TimelineKind.APPROVAL,
        "Approved by human operator" if approved else "Rejected by human operator",
        (
            ("Simulated remediation recorded as approved. No plant equipment was controlled. " if approved
             else "Simulated remediation recorded as rejected. ")
            + (note or "")
        ).strip(),
        state=inspection.state,
        data={"incident_id": incident.id, "approved": approved},
    )
    return incident


@router.post("/{inspection_id}/resolve", response_model=Inspection)
async def mark_resolved(
    inspection_id: str,
    resolved: bool = Query(...),
    context: AppContext = Depends(get_context),
) -> Inspection:
    """Record whether the user's problem was actually fixed (home mode)."""
    inspection = await _load(context, inspection_id)
    inspection.resolved = resolved
    inspection.outcome = (
        "The user reported that the problem is resolved."
        if resolved
        else "The user reported that the problem is not resolved; further investigation is needed."
    )
    inspection.state = InspectionState.COMPLETED
    inspection.updated_at = utcnow()
    await context.repo.update_inspection(inspection)
    await context.repo.add_timeline(
        inspection_id,
        TimelineKind.APPROVAL,
        "Outcome confirmed by user",
        inspection.outcome,
        state=inspection.state,
        data={"resolved": resolved},
    )
    return await _load(context, inspection_id)
