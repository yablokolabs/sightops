"""Repository round-trips.

The tool trace and the incident record are the audit trail, so persistence is
tested for ordering and for fidelity across a JSON round-trip.
"""

from __future__ import annotations

import uuid

from app.models.schemas import (
    Assessment,
    Incident,
    IncidentStatus,
    Inspection,
    InspectionMode,
    Measurement,
    Provenance,
    Severity,
    TimelineKind,
    ToolCallRecord,
    utcnow,
)


async def _make_inspection(repo, *, demo_mode=False, created_at=None):
    inspection = Inspection(
        id=uuid.uuid4().hex,
        mode=InspectionMode.INDUSTRIAL,
        profile_id="industrial_panel_v1",
        problem_statement="pump pressure alarm",
        appliance="mock equipment",
        demo_mode=demo_mode,
        **({"created_at": created_at, "updated_at": created_at} if created_at else {}),
    )
    await repo.create_inspection(inspection)
    return inspection


async def _add_image(repo, inspection_id, sequence):
    image_id = uuid.uuid4().hex
    await repo.add_image(
        image_id=image_id,
        inspection_id=inspection_id,
        original_name=f"observation-{sequence}.png",
        content_type="image/png",
        sha256="0" * 64,
        width=1280,
        height=720,
        stored_path=f"{inspection_id}/{image_id}.png",
        role="primary" if sequence == 1 else "follow_up",
        sequence=sequence,
        created_at=utcnow().isoformat(),
    )
    return image_id


async def test_inspection_round_trip_preserves_flags(repo):
    created = await _make_inspection(repo, demo_mode=True)

    fetched = await repo.get_inspection(created.id)

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.mode is InspectionMode.INDUSTRIAL
    assert fetched.profile_id == "industrial_panel_v1"
    assert fetched.problem_statement == "pump pressure alarm"
    assert fetched.appliance == "mock equipment"
    assert fetched.demo_mode is True


async def test_missing_inspection_returns_none(repo):
    assert await repo.get_inspection("does-not-exist") is None


async def test_assessment_and_pending_request_survive_a_round_trip(repo):
    from app.models.schemas import InspectionState, ReinspectionRequest

    inspection = await _make_inspection(repo)
    inspection.assessment = Assessment(
        summary="Pressure is above the limit.",
        confidence=0.83,
        recommended_next_step="Raise an incident.",
        user_message="The gauge reads high.",
    )
    inspection.pending_request = ReinspectionRequest(
        target_region="pressure_gauge_01",
        instruction="Re-image square-on.",
        reason="the dial could not be measured",
    )
    inspection.state = InspectionState.AWAITING_APPROVAL
    inspection.step_count = 4
    inspection.tool_call_count = 5
    await repo.update_inspection(inspection)

    fetched = await repo.get_inspection(inspection.id)

    assert fetched is not None
    assert fetched.state is InspectionState.AWAITING_APPROVAL
    assert fetched.assessment is not None
    assert fetched.assessment.confidence == 0.83
    assert fetched.pending_request is not None
    assert fetched.pending_request.target_region == "pressure_gauge_01"
    assert fetched.step_count == 4
    assert fetched.tool_call_count == 5


async def test_observations_come_back_in_sequence_order_with_their_analysis(repo, engine, industrial_profile):
    from app.fixtures.generate_panels import scenario_fault_closeup

    inspection = await _make_inspection(repo)
    first = await _add_image(repo, inspection.id, sequence=1)
    second = await _add_image(repo, inspection.id, sequence=2)
    await repo.add_observation(uuid.uuid4().hex, inspection.id, first, None, utcnow().isoformat())
    await repo.add_observation(uuid.uuid4().hex, inspection.id, second, None, utcnow().isoformat())

    analysis = engine.analyze(
        scenario_fault_closeup().image, image_id=second, profile=industrial_profile
    )
    await repo.update_observation_analysis(second, analysis)

    observations = await repo.list_observations(inspection.id)

    assert [o.sequence for o in observations] == [1, 2]
    assert [o.image_id for o in observations] == [first, second]
    assert observations[0].analysis is None
    assert observations[1].analysis is not None
    assert observations[1].analysis.profile_id == industrial_profile.profile_id
    assert len(observations[1].analysis.measurements) == len(industrial_profile.regions)
    # The stored measurement keeps its provenance, not just its value.
    gauge = next(
        m for m in observations[1].analysis.measurements if m.component_type == "analog_gauge"
    )
    assert gauge.provenance is Provenance.MEASURED

    # Both images are registered, and only the analysed one carries a result.
    images = await repo.list_images(inspection.id)
    assert [image["sequence"] for image in images] == [1, 2]
    assert sum(1 for o in observations if o.analysis is not None) == 1


async def test_observation_count_matches_the_stored_rows(repo):
    inspection = await _make_inspection(repo)
    for sequence in (1, 2, 3):
        image_id = await _add_image(repo, inspection.id, sequence=sequence)
        await repo.add_observation(
            uuid.uuid4().hex, inspection.id, image_id, None, utcnow().isoformat()
        )

    fetched = await repo.get_inspection(inspection.id)

    assert fetched is not None
    assert fetched.observation_count == 3
    assert await repo.observation_count(inspection.id) == 3


async def test_next_sequence_increments(repo):
    inspection = await _make_inspection(repo)

    assert await repo.next_sequence(inspection.id) == 1
    await _add_image(repo, inspection.id, sequence=1)
    assert await repo.next_sequence(inspection.id) == 2
    await _add_image(repo, inspection.id, sequence=2)
    assert await repo.next_sequence(inspection.id) == 3


async def test_timeline_comes_back_in_insertion_order(repo):
    inspection = await _make_inspection(repo)

    for index in range(4):
        await repo.add_timeline(
            inspection.id,
            TimelineKind.DECISION,
            f"decision {index}",
            f"detail {index}",
            data={"index": index},
        )

    entries = await repo.list_timeline(inspection.id)

    assert [e.title for e in entries] == [f"decision {i}" for i in range(4)]
    assert [e.id for e in entries] == sorted(e.id for e in entries)
    assert entries[2].data == {"index": 2}
    assert entries[0].kind is TimelineKind.DECISION


async def test_tool_calls_round_trip_with_their_arguments(repo):
    inspection = await _make_inspection(repo)

    await repo.add_tool_call(
        ToolCallRecord(
            inspection_id=inspection.id,
            step=1,
            tool="read_gauge",
            arguments={"region_id": "pressure_gauge_01"},
            ok=True,
            result={"value": 87.16, "unit": "PSI"},
            duration_ms=12.5,
            source="policy",
        )
    )
    await repo.add_tool_call(
        ToolCallRecord(
            inspection_id=inspection.id,
            step=2,
            tool="request_new_view",
            arguments={"target_region": "pressure_gauge_01"},
            ok=False,
            error="boom",
            source="model",
        )
    )

    calls = await repo.list_tool_calls(inspection.id)

    assert [c.tool for c in calls] == ["read_gauge", "request_new_view"]
    assert calls[0].arguments == {"region_id": "pressure_gauge_01"}
    assert calls[0].result["value"] == 87.16
    assert calls[0].source == "policy"
    assert calls[0].ok is True
    assert calls[1].ok is False
    assert calls[1].error == "boom"
    assert calls[1].source == "model"


async def test_incident_round_trips_measurements_and_evidence_ids(repo):
    inspection = await _make_inspection(repo)
    first = await _add_image(repo, inspection.id, sequence=1)
    second = await _add_image(repo, inspection.id, sequence=2)

    measurement = Measurement(
        component_id="pressure_gauge_01",
        component_type="analog_gauge",
        state="HIGH",
        value=87.16,
        unit="PSI",
        confidence=0.96,
        method="opencv_needle_geometry",
        details={"ray_coverage": 1.0},
    )
    incident = Incident(
        id=uuid.uuid4().hex,
        inspection_id=inspection.id,
        title="Abnormal condition",
        summary="Pressure above the limit.",
        severity=Severity.HIGH,
        status=IncidentStatus.AWAITING_APPROVAL,
        evidence_image_ids=[first, second],
        measurements=[measurement],
        proposed_action="Simulated remediation.",
        approval_required=True,
    )
    await repo.create_incident(incident)

    fetched = await repo.get_incident(incident.id)

    assert fetched is not None
    assert fetched.evidence_image_ids == [first, second]
    assert fetched.approval_required is True
    assert len(fetched.measurements) == 1
    assert fetched.measurements[0].value == 87.16
    assert fetched.measurements[0].unit == "PSI"
    assert fetched.measurements[0].details == {"ray_coverage": 1.0}
    assert fetched.severity is Severity.HIGH

    listed = await repo.list_incidents()
    assert [i.id for i in listed] == [incident.id]


async def test_incident_status_update_is_persisted(repo):
    inspection = await _make_inspection(repo)
    incident = Incident(
        id=uuid.uuid4().hex,
        inspection_id=inspection.id,
        title="Abnormal condition",
        summary="Pressure above the limit.",
        severity=Severity.HIGH,
    )
    await repo.create_incident(incident)

    incident.status = IncidentStatus.REMEDIATION_APPROVED
    incident.resolution_note = "Reviewed."
    incident.updated_at = utcnow()
    await repo.update_incident(incident)

    fetched = await repo.get_incident(incident.id)

    assert fetched is not None
    assert fetched.status is IncidentStatus.REMEDIATION_APPROVED
    assert fetched.resolution_note == "Reviewed."


async def test_list_inspections_is_newest_first(repo):
    from datetime import datetime, timezone

    older = await _make_inspection(
        repo, created_at=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    )
    newer = await _make_inspection(
        repo, created_at=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
    )

    listed = await repo.list_inspections()

    assert [i.id for i in listed] == [newer.id, older.id]
