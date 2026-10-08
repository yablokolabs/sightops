"""Safety guardrails.

The build specification is explicit that SightOps is decision support and must
never control real machinery, that remediation is simulated, and that
consequential actions need explicit human approval. These tests check the parts
of that claim that are mechanical rather than rhetorical.
"""

from __future__ import annotations

from app.agent.prompts import INDUSTRIAL_ADDENDUM, SYSTEM_PROMPT, system_prompt
from app.agent.tools import CreateIncidentArgs, ToolContext
from app.fixtures.generate_panels import scenario_fault_closeup
from app.models.schemas import InspectionMode, InspectionState

#: Names that would indicate a tool could actually act on equipment.
ACTUATION_WORDS = ("control", "actuate", "execute", "shutdown", "energise", "energize", "switch_on")


def test_system_prompt_states_that_sightops_never_controls_machinery():
    lowered = SYSTEM_PROMPT.lower()

    assert "never controls real machinery" in lowered
    assert "decision support" in lowered
    assert "simulated" in lowered
    assert "human approval" in lowered


def test_system_prompt_forbids_unsafe_repair_advice():
    lowered = SYSTEM_PROMPT.lower()

    for forbidden in (
        "opening energised equipment",
        "bypassing interlocks",
        "modifying",
        "disabling protective devices",
    ):
        assert forbidden in lowered


def test_system_prompt_tells_the_agent_to_represent_uncertainty():
    lowered = SYSTEM_PROMPT.lower()

    assert "represent uncertainty clearly" in lowered
    assert "never" in lowered and "invent a numeric reading" in lowered


def test_industrial_prompt_repeats_the_simulation_requirement():
    prompt = system_prompt(InspectionMode.INDUSTRIAL).lower()

    assert "mock" in prompt
    assert "simulated" in prompt
    assert "approved by a human" in prompt
    assert INDUSTRIAL_ADDENDUM in system_prompt(InspectionMode.INDUSTRIAL)


def test_incidents_require_approval_by_default():
    arguments = CreateIncidentArgs(
        title="t", summary="s", severity="high", proposed_action="simulated remediation"
    )

    assert arguments.requires_approval is True


def test_no_tool_context_member_suggests_actuation():
    from app.vision.profiles import INDUSTRIAL_PANEL

    context = ToolContext(
        engine=None,
        profile=INDUSTRIAL_PANEL,
        images={},
        analyses={},
        ordered_image_ids=[],
    )
    names = [name.lower() for name in dir(context) if not name.startswith("__")]
    names += [name.lower() for name in dir(ToolContext) if not name.startswith("__")]

    offending = [
        name for name in names if any(word in name for word in ACTUATION_WORDS)
    ]
    assert offending == [], (
        f"these names suggest a tool could act on equipment: {offending}. SightOps has no "
        f"actuation path: every remediation is recorded, never executed."
    )


async def test_a_faulty_inspection_cannot_complete_without_approval(
    repo, engine, settings, make_inspection, attach_image
):
    """The whole point of the approval gate, asserted end to end."""
    from app.agent.loop import InspectionAgent

    agent = InspectionAgent(repo, engine, provider=None, settings=settings)
    inspection = await make_inspection(mode=InspectionMode.INDUSTRIAL, demo_mode=True)
    await attach_image(inspection, scenario_fault_closeup())

    await agent.run(inspection.id)

    final = await repo.get_inspection(inspection.id)
    assert final is not None
    assert final.state is InspectionState.AWAITING_APPROVAL
    assert final.state is not InspectionState.COMPLETED
    assert final.resolved is None

    incident = await repo.get_incident(final.incident_id)
    assert incident is not None
    assert incident.approval_required is True
    assert incident.status.value == "awaiting_approval"


async def test_the_approval_record_says_nothing_was_executed(
    repo, engine, settings, make_inspection, attach_image
):
    from app.agent.loop import InspectionAgent
    from app.api.deps import build_context
    from app.api.inspections import _decide

    agent = InspectionAgent(repo, engine, provider=None, settings=settings)
    inspection = await make_inspection(mode=InspectionMode.INDUSTRIAL, demo_mode=True)
    await attach_image(inspection, scenario_fault_closeup())
    await agent.run(inspection.id)

    context = await build_context(settings)
    try:
        await _decide(context, inspection.id, approved=True, note="Approved.")
    finally:
        await context.aclose()

    final = await repo.get_inspection(inspection.id)
    assert final is not None
    assert final.outcome is not None
    lowered = final.outcome.lower()
    assert "nothing was executed" in lowered or "no plant equipment" in lowered
    assert "mock" in lowered

    timeline = await repo.list_timeline(inspection.id)
    approvals = [entry for entry in timeline if entry.kind.value == "approval"]
    assert approvals
    assert "No plant equipment was controlled" in approvals[-1].detail


def test_proposed_actions_are_labelled_simulated(engine, industrial_profile):
    """Every action the policy proposes must say it is simulated."""
    from app.agent.policy import decide

    scene = scenario_fault_closeup()
    analysis = engine.analyze(scene.image, image_id="img1", profile=industrial_profile)
    context = ToolContext(
        engine=engine,
        profile=industrial_profile,
        images={"img1": scene.image},
        analyses={"img1": analysis},
        ordered_image_ids=["img1"],
    )

    decision = decide(context, mode="industrial", diagnosed=True)

    assert decision.tool == "create_incident"
    proposed = decision.arguments["proposed_action"].lower()
    assert "simulated" in proposed
    assert "no plant equipment is connected" in proposed


def test_escalation_to_a_professional_is_available_to_the_agent():
    """The prompt must allow the honest answer \"this needs a qualified person\"."""
    lowered = SYSTEM_PROMPT.lower()
    assert "escalate" in lowered
    assert "qualified professional" in lowered
