"""Scripted demonstration flows.

These routes exist so the household and industrial demonstrations can be
reproduced exactly, in the UI or during a screen recording, without depending on
a live camera or on a language model.

They are **not** canned results. Each step writes a real generated image to
evidence storage and hands it to the normal inspection path, so OpenCV performs
the same measurement it would for an upload. What is scripted is only *which
photograph arrives when*.

The flows are labelled ``DEMO MODE`` in the UI and in every timeline entry.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.api.deps import AppContext, get_context
from app.fixtures.generate_panels import (
    Degradation,
    PanelScene,
    render_dishwasher_panel,
    render_industrial_panel,
)
from app.models.schemas import (
    Inspection,
    InspectionMode,
    InspectionState,
    TimelineKind,
    utcnow,
)
from app.storage.evidence import sha256_of
from app.vision.annotate import encode_png
from app.vision.profiles import DISHWASHER_PANEL, INDUSTRIAL_PANEL

router = APIRouter(prefix="/api/demo", tags=["demo"])


def _industrial_steps() -> list[tuple[str, PanelScene, str]]:
    """(caption, scene, note) for the industrial pump-station walkthrough."""
    return [
        (
            "Pump station photographed from an angle, with a reflection across the gauge",
            render_industrial_panel(
                pressure_psi=87.0,
                warning="RED",
                status="OFF",
                switch="UP",
                degrade=Degradation(perspective=0.13, glare=0.30, noise_sigma=3.0),
                seed=23,
            ),
            "The warning lamp reads clearly but the gauge cannot be measured, so SightOps asks "
            "for a better view instead of guessing.",
        ),
        (
            "Same panel re-imaged square-on with diffuse light",
            render_industrial_panel(
                pressure_psi=87.0,
                warning="RED",
                status="OFF",
                switch="UP",
                degrade=Degradation(noise_sigma=1.5),
                seed=24,
            ),
            "The gauge now measures cleanly and the abnormal condition is confirmed.",
        ),
    ]


def _home_steps() -> list[tuple[str, PanelScene, str]]:
    return [
        (
            "Dishwasher fascia photographed from across the kitchen",
            render_dishwasher_panel(
                lit=True,
                glyph="1:42",
                power="GREEN",
                start="OFF",
                degrade=Degradation(blur_sigma=1.3, resolution_scale=0.40, brightness=1.05, noise_sigma=3.0),
                seed=31,
            ),
            "Too far away to read reliably, so SightOps asks for a closer photograph.",
        ),
        (
            "Close-up of the same fascia",
            render_dishwasher_panel(
                lit=True, glyph="1:42", power="GREEN", start="OFF", degrade=Degradation(noise_sigma=1.2), seed=32
            ),
            "The display is lit and the power lamp is green, which changes what the problem can be.",
        ),
    ]


_FLOWS = {
    "industrial": (
        InspectionMode.INDUSTRIAL,
        INDUSTRIAL_PANEL.profile_id,
        _industrial_steps,
        "Pump discharge pressure alarm. The panel shows a red warning lamp.",
    ),
    "home": (
        InspectionMode.HOME,
        DISHWASHER_PANEL.profile_id,
        _home_steps,
        "My dishwasher isn't working. The panel is lit but nothing happens when I press start.",
    ),
}


@router.get("/flows")
async def list_flows() -> dict:
    return {
        "flows": [
            {
                "id": key,
                "mode": entry[0].value,
                "profile_id": entry[1],
                "steps": len(entry[2]()),
                "problem": entry[3],
            }
            for key, entry in _FLOWS.items()
        ],
        "note": "Demo flows use generated mock equipment images and real OpenCV measurement.",
    }


@router.post("/{flow}", response_model=Inspection, status_code=201)
async def start_flow(flow: str, context: AppContext = Depends(get_context)) -> Inspection:
    if flow not in _FLOWS:
        raise HTTPException(
            status_code=404, detail=f"unknown demo flow {flow!r}; try one of {', '.join(_FLOWS)}"
        )
    mode, profile_id, steps_loader, problem = _FLOWS[flow]
    steps = steps_loader()

    inspection = Inspection(
        id=uuid.uuid4().hex,
        mode=mode,
        profile_id=profile_id,
        problem_statement=problem,
        appliance="mock equipment" if mode == InspectionMode.INDUSTRIAL else "dishwasher",
        demo_mode=True,
    )
    await context.repo.create_inspection(inspection)
    await context.repo.add_timeline(
        inspection.id,
        TimelineKind.REASONING,
        "DEMO MODE — scripted observation sequence",
        (
            "This walkthrough feeds real generated equipment photographs to the normal inspection "
            "pipeline. Every measurement below is produced by OpenCV; only the timing of the "
            "photographs is scripted."
        ),
        state=InspectionState.CREATED,
    )
    await _attach(context, inspection, steps[0])
    await context.repo.add_timeline(
        inspection.id,
        TimelineKind.OBSERVATION,
        "Scripted step 1 of 2",
        steps[0][2],
        state=InspectionState.CREATED,
    )
    await context.agent.run(inspection.id)
    updated = await context.repo.get_inspection(inspection.id)
    assert updated is not None
    return updated


@router.post("/{inspection_id}/next-observation", response_model=Inspection)
async def next_observation(
    inspection_id: str, context: AppContext = Depends(get_context)
) -> Inspection:
    inspection = await context.repo.get_inspection(inspection_id)
    if inspection is None:
        raise HTTPException(status_code=404, detail=f"no inspection with id {inspection_id}")
    if inspection.profile_id not in {INDUSTRIAL_PANEL.profile_id, DISHWASHER_PANEL.profile_id}:
        raise HTTPException(status_code=409, detail="this inspection is not a demo flow")

    flow = "industrial" if inspection.profile_id == INDUSTRIAL_PANEL.profile_id else "home"
    steps = _FLOWS[flow][2]()
    taken = len([o for o in inspection.observations])
    if taken >= len(steps):
        raise HTTPException(
            status_code=409,
            detail=f"this demo flow has no more scripted observations (it has {len(steps)} steps)",
        )

    caption, scene, note = steps[taken]
    await _attach(context, inspection, (caption, scene, note))
    await context.repo.add_timeline(
        inspection.id,
        TimelineKind.OBSERVATION,
        f"Scripted step {taken + 1} of {len(steps)}",
        note,
        state=inspection.state,
    )
    inspection.pending_request = None
    await context.repo.update_inspection(inspection)
    await context.agent.run(inspection.id)
    updated = await context.repo.get_inspection(inspection.id)
    assert updated is not None
    return updated


async def _attach(context: AppContext, inspection: Inspection, step) -> None:
    caption, scene, _note = step
    image_id = uuid.uuid4().hex
    data = encode_png(scene.image)
    key = context.evidence.put(inspection.id, image_id, "png", data)
    height, width = scene.image.shape[:2]
    sequence = await context.repo.next_sequence(inspection.id)

    await context.repo.add_image(
        image_id=image_id,
        inspection_id=inspection.id,
        original_name=f"{inspection.profile_id}-{sequence}.png",
        content_type="image/png",
        sha256=sha256_of(data),
        width=width,
        height=height,
        stored_path=key,
        role="primary" if sequence == 1 else "follow_up",
        sequence=sequence,
        created_at=utcnow().isoformat(),
    )
    await context.repo.add_observation(
        uuid.uuid4().hex, inspection.id, image_id, None, utcnow().isoformat()
    )


@router.get("/{flow}/preview/{index}")
async def preview(flow: str, index: int) -> Response:
    """Render a demo step on demand, so the same generator produces the frames."""
    if flow not in _FLOWS:
        raise HTTPException(status_code=404, detail=f"unknown demo flow {flow!r}")
    steps = _FLOWS[flow][2]()
    if index < 0 or index >= len(steps):
        raise HTTPException(status_code=404, detail=f"flow {flow} has {len(steps)} steps")
    return Response(content=encode_png(steps[index][1].image), media_type="image/png")
