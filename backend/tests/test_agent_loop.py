"""The full agentic inspection loop, end to end.

This is the behavioural test for the whole product claim: SightOps measures what
it can, notices that some evidence is not good enough, asks for a better
photograph, re-measures, and only then concludes and escalates. The run uses the
deterministic policy (``provider=None``, ``demo_mode=True``) so it is
reproducible and costs nothing, and every number it acts on comes from OpenCV.
"""

from __future__ import annotations

import pytest

from app.agent.loop import InspectionAgent
from app.fixtures.generate_panels import (
    scenario_dishwasher_closeup,
    scenario_fault_closeup,
    scenario_fault_distant,
    scenario_normal,
)
from app.models.schemas import InspectionMode, InspectionState


@pytest.fixture
def agent(repo, engine, settings):
    return InspectionAgent(repo, engine, provider=None, settings=settings)


async def test_industrial_walkthrough_asks_for_better_evidence_then_escalates(
    repo, agent, engine, settings, make_inspection, attach_image
):
    inspection = await make_inspection(mode=InspectionMode.INDUSTRIAL, demo_mode=True)

    # -- observation 1: the warning lamp reads, the gauge does not ------------
    await attach_image(inspection, scenario_fault_distant())
    first = await agent.run(inspection.id)

    assert first.degraded is False
    after_first = await repo.get_inspection(inspection.id)
    assert after_first is not None
    assert after_first.state is InspectionState.WAITING_FOR_USER
    assert after_first.pending_request is not None
    assert after_first.pending_request.target_region == "pressure_gauge_01"
    assert after_first.pending_request.instruction
    assert isinstance(after_first.pending_request.reason, str)
    assert after_first.pending_request.reason.strip(), (
        "the request must explain why better evidence is needed"
    )
    # Nothing was concluded, and no incident exists yet.
    assert after_first.incident_id is None
    assert after_first.assessment is None

    calls = await repo.list_tool_calls(inspection.id)
    assert [c.tool for c in calls] == ["inspect_panel", "request_new_view"]
    assert all(c.source == "policy" for c in calls)

    # -- observation 2: the same frame, properly captured --------------------
    await attach_image(inspection, scenario_fault_closeup())
    second = await agent.run(inspection.id)

    final = await repo.get_inspection(inspection.id)
    assert final is not None
    assert final.state is InspectionState.AWAITING_APPROVAL
    assert final.incident_id is not None
    assert final.assessment is not None
    # The recorded conclusion quotes the measured value, so it is traceable.
    assert "PSI" in final.assessment.summary
    assert "87" in final.assessment.summary

    incident = await repo.get_incident(final.incident_id)
    assert incident is not None
    assert incident.approval_required is True
    assert "SIMULATED" in incident.proposed_action.upper()
    assert incident.measurements, "the incident must carry the evidence it was raised from"

    tool_names = [c.tool for c in await repo.list_tool_calls(inspection.id)]
    assert tool_names == [
        "inspect_panel",
        "request_new_view",
        "inspect_panel",
        "compare_observations",
        "record_diagnosis",
        "create_incident",
        "request_human_approval",
    ]
    assert all(c.source == "policy" for c in await repo.list_tool_calls(inspection.id))

    # -- bounds --------------------------------------------------------------
    # step_count and tool_call_count accumulate across runs, while the loop
    # enforces its budgets per run; the cumulative totals must still fit.
    assert final.tool_call_count <= settings.max_tool_calls
    assert final.step_count <= settings.max_agent_steps
    assert second.tool_calls <= settings.max_tool_calls

    # -- the human gate ------------------------------------------------------
    assert final.state is not InspectionState.COMPLETED, (
        "an abnormal industrial condition must not complete without approval"
    )


async def test_approval_completes_the_inspection_and_records_the_decision(
    repo, agent, settings, make_inspection, attach_image
):
    inspection = await make_inspection(mode=InspectionMode.INDUSTRIAL, demo_mode=True)
    await attach_image(inspection, scenario_fault_distant())
    await agent.run(inspection.id)
    await attach_image(inspection, scenario_fault_closeup())
    await agent.run(inspection.id)

    pending = await repo.get_inspection(inspection.id)
    assert pending is not None and pending.incident_id is not None

    # Drive the real approval path: the same handler the /approve endpoint calls,
    # against the same database.
    from app.api.deps import build_context
    from app.api.inspections import _decide

    context = await build_context(settings)
    try:
        incident = await _decide(
            context, inspection.id, approved=True, note="Operator reviewed the evidence."
        )
    finally:
        await context.aclose()

    assert incident.status.value == "remediation_approved"
    assert incident.resolution_note == "Operator reviewed the evidence."

    final = await repo.get_inspection(inspection.id)
    assert final is not None
    assert final.state is InspectionState.COMPLETED
    assert final.resolved is True
    assert final.outcome is not None
    assert "mock" in final.outcome.lower() or "No plant equipment" in final.outcome

    timeline = await repo.list_timeline(inspection.id)
    assert any(entry.kind.value == "approval" for entry in timeline)


async def test_rejection_records_a_rejection_and_takes_no_action(
    repo, agent, settings, make_inspection, attach_image
):
    inspection = await make_inspection(mode=InspectionMode.INDUSTRIAL, demo_mode=True)
    await attach_image(inspection, scenario_fault_closeup())
    await agent.run(inspection.id)

    from app.api.deps import build_context
    from app.api.inspections import _decide

    context = await build_context(settings)
    try:
        incident = await _decide(context, inspection.id, approved=False, note="Not authorised.")
    finally:
        await context.aclose()

    assert incident.status.value == "remediation_rejected"
    final = await repo.get_inspection(inspection.id)
    assert final is not None
    assert final.state is InspectionState.COMPLETED
    assert final.resolved is False
    assert "rejected" in (final.outcome or "").lower()


async def test_a_healthy_inspection_never_creates_an_incident(
    repo, agent, make_inspection, attach_image
):
    inspection = await make_inspection(mode=InspectionMode.INDUSTRIAL, demo_mode=True)
    await attach_image(inspection, scenario_normal())

    await agent.run(inspection.id)

    final = await repo.get_inspection(inspection.id)
    assert final is not None
    assert final.incident_id is None
    assert final.state is InspectionState.COMPLETED
    assert final.assessment is not None
    assert "No fault found" in final.assessment.summary

    tool_names = [c.tool for c in await repo.list_tool_calls(inspection.id)]
    assert tool_names == ["inspect_panel", "record_diagnosis"]


async def test_home_mode_gives_advice_without_raising_an_incident(
    repo, agent, make_inspection, attach_image
):
    inspection = await make_inspection(
        mode=InspectionMode.HOME, demo_mode=True, problem="My dishwasher isn't working."
    )
    await attach_image(inspection, scenario_dishwasher_closeup())

    await agent.run(inspection.id)

    final = await repo.get_inspection(inspection.id)
    assert final is not None
    assert final.incident_id is None
    assert final.state is InspectionState.COMPLETED
    assert final.assessment is not None
    # Plain language, and no error codes were invented.
    assert len(final.assessment.user_message) < 600


async def test_the_run_is_labelled_as_demo_mode_in_the_timeline(
    repo, agent, make_inspection, attach_image
):
    inspection = await make_inspection(demo_mode=True)
    await attach_image(inspection, scenario_normal())

    await agent.run(inspection.id)

    timeline = await repo.list_timeline(inspection.id)
    assert any(
        "DEMO MODE" in entry.title or "DEMO MODE" in entry.detail for entry in timeline
    ), "deterministic behaviour must not be presented as model reasoning"
    assert any(entry.data.get("policy") == "deterministic_demo" for entry in timeline)


async def test_a_missing_provider_degrades_to_the_policy_and_says_so(
    repo, engine, settings, make_inspection, attach_image
):
    """A live-mode inspection with no model must still work, and must be honest."""
    agent = InspectionAgent(repo, engine, provider=None, settings=settings)
    inspection = await make_inspection(demo_mode=False)
    await attach_image(inspection, scenario_normal())

    result = await agent.run(inspection.id)

    assert result.degraded is True
    timeline = await repo.list_timeline(inspection.id)
    assert any(entry.kind.value == "error" for entry in timeline)
    assert any("Live reasoning unavailable" in entry.title for entry in timeline)

    final = await repo.get_inspection(inspection.id)
    assert final is not None
    assert final.state is InspectionState.COMPLETED
    # The measurement still happened: the degradation is in the reasoning only.
    observations = await repo.list_observations(inspection.id)
    assert observations[0].analysis is not None


async def test_running_without_images_does_nothing_and_says_so(repo, agent, make_inspection):
    inspection = await make_inspection(demo_mode=True)

    result = await agent.run(inspection.id)

    assert result.state is InspectionState.CREATED
    timeline = await repo.list_timeline(inspection.id)
    assert any("Nothing to inspect yet" in entry.title for entry in timeline)


async def test_unknown_inspection_raises(agent):
    with pytest.raises(KeyError):
        await agent.run("no-such-inspection")


async def test_annotated_evidence_is_produced_for_each_analysed_observation(
    repo, agent, settings, make_inspection, attach_image
):
    inspection = await make_inspection(demo_mode=True)
    image_id = await attach_image(inspection, scenario_normal())

    await agent.run(inspection.id)

    record = await repo.get_image(image_id)
    assert record is not None
    assert record["annotated_path"], "the evidence overlay must be generated by the run"
    from app.storage.evidence import LocalEvidenceStorage

    storage = LocalEvidenceStorage(settings.evidence_dir)
    assert storage.exists(record["annotated_path"])
    assert len(storage.get(record["annotated_path"])) > 1000
