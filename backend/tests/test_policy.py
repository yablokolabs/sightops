"""The deterministic demonstration policy.

The build specification forbids replacing the agent with a fixed sequence of
hardcoded responses. These tests are the evidence that the policy is a real
function of the measurements: a healthy panel and a faulty one go down different
paths, and a panel the vision engine could not measure produces a request for
better evidence rather than a conclusion.
"""

from __future__ import annotations

from app.agent.policy import decide
from app.agent.tools import ToolContext
from app.fixtures.generate_panels import (
    render_industrial_panel,
    scenario_fault_closeup,
    scenario_fault_distant,
    scenario_normal,
)


def _context(engine, profile, scenes: dict[str, object]):
    analyses = {}
    images = {}
    for image_id, scene in scenes.items():
        images[image_id] = scene.image
        analyses[image_id] = engine.analyze(
            scene.image, image_id=image_id, profile=profile
        )
    return ToolContext(
        engine=engine,
        profile=profile,
        images=images,
        analyses=analyses,
        ordered_image_ids=list(scenes),
    )


def test_no_measurements_means_measure_first(engine, industrial_profile):
    context = ToolContext(
        engine=engine,
        profile=industrial_profile,
        images={"img1": scenario_normal().image},
        analyses={},
        ordered_image_ids=["img1"],
    )

    decision = decide(context, mode="industrial")

    assert decision.tool == "inspect_panel"
    assert decision.arguments["image_id"] == "img1"
    assert decision.rationale


def test_a_healthy_panel_is_concluded_not_escalated(engine, industrial_profile):
    context = _context(engine, industrial_profile, {"img1": scenario_normal()})

    decision = decide(context, mode="industrial")

    assert decision.tool in {"record_diagnosis", "compare_observations"}
    assert decision.tool != "create_incident"
    assert decision.tool != "request_human_approval"
    if decision.tool == "record_diagnosis":
        assert "No fault found" in decision.arguments["summary"]
        assert decision.arguments["confidence"] > 0.5


def test_a_healthy_panel_never_creates_an_incident_however_far_the_run_goes(
    engine, industrial_profile
):
    """Walk the whole policy chain on a healthy panel and watch for escalation."""
    context = _context(engine, industrial_profile, {"img1": scenario_normal()})
    seen: list[str] = []

    for _ in range(6):
        decision = decide(
            context,
            mode="industrial",
            diagnosed="record_diagnosis" in seen,
            incident_created="create_incident" in seen,
            approval_requested="request_human_approval" in seen,
        )
        seen.append(decision.tool)
        if decision.tool == "record_diagnosis" and seen.count("record_diagnosis") > 1:
            break

    assert "create_incident" not in seen
    assert "request_human_approval" not in seen
    assert "request_new_view" not in seen


def test_a_faulty_panel_reaches_incident_then_approval(engine, industrial_profile):
    context = _context(engine, industrial_profile, {"img1": scenario_fault_closeup()})

    diagnosis = decide(context, mode="industrial")
    assert diagnosis.tool == "record_diagnosis"
    assert "87" in diagnosis.arguments["summary"]
    assert "PSI" in diagnosis.arguments["summary"]

    incident = decide(context, mode="industrial", diagnosed=True)
    assert incident.tool == "create_incident"
    assert incident.arguments["requires_approval"] is True
    assert incident.arguments["severity"] == "high"

    approval = decide(
        context, mode="industrial", diagnosed=True, incident_created=True
    )
    assert approval.tool == "request_human_approval"
    assert approval.arguments["action"]


def test_a_faulty_panel_produces_a_different_path_from_a_healthy_one(engine, industrial_profile):
    healthy = decide(_context(engine, industrial_profile, {"img1": scenario_normal()}), mode="industrial")
    faulty = decide(
        _context(engine, industrial_profile, {"img1": scenario_fault_closeup()}), mode="industrial"
    )

    assert healthy.arguments["summary"] != faulty.arguments["summary"]
    assert "No fault found" in healthy.arguments["summary"]
    assert "Abnormal condition confirmed" in faulty.arguments["summary"]


def test_unreadable_evidence_requests_a_better_photograph(engine, industrial_profile):
    """The defining behaviour: low-confidence evidence is investigated, not guessed."""
    context = _context(engine, industrial_profile, {"img1": scenario_fault_distant()})

    decision = decide(context, mode="industrial", reinspection_rounds=0)

    assert decision.tool == "request_new_view"
    assert decision.arguments["target_region"] == "pressure_gauge_01"
    assert decision.arguments["instruction"]
    assert decision.arguments["reason"]


def test_reinspection_is_bounded(engine, industrial_profile):
    """Once the budget is spent the policy stops asking and concludes instead."""
    context = _context(engine, industrial_profile, {"img1": scenario_fault_distant()})

    decision = decide(context, mode="industrial", reinspection_rounds=2, max_reinspection_rounds=2)

    assert decision.tool != "request_new_view"


def test_home_mode_never_escalates_to_an_incident(engine, dishwasher_profile):
    """Home troubleshooting is advice only; no incident is raised for a dishwasher."""
    from app.fixtures.generate_panels import scenario_dishwasher_closeup

    context = _context(engine, dishwasher_profile, {"img1": scenario_dishwasher_closeup()})

    decision = decide(context, mode="home")

    assert decision.tool == "record_diagnosis"
    assert "incident" not in decision.arguments["summary"].lower()


def test_home_mode_instruction_is_plain_language(engine, dishwasher_profile):
    from app.fixtures.generate_panels import scenario_dishwasher_wide

    context = _context(engine, dishwasher_profile, {"img1": scenario_dishwasher_wide()})

    decision = decide(context, mode="home", reinspection_rounds=0)

    if decision.tool == "request_new_view":
        instruction = decision.arguments["instruction"]
        assert "photo" in instruction.lower()
        # No engineering jargon in a household instruction.
        for jargon in ("specular", "diffuse", "square-on", "ROI"):
            assert jargon not in instruction


def test_industrial_instruction_asks_for_a_specific_re_framing(engine, industrial_profile):
    context = _context(engine, industrial_profile, {"img1": scenario_fault_distant()})

    decision = decide(context, mode="industrial")

    assert decision.tool == "request_new_view"
    assert "square-on" in decision.arguments["instruction"]


def test_a_second_observation_is_compared_before_being_interpreted(engine, industrial_profile):
    context = _context(
        engine,
        industrial_profile,
        {"img1": scenario_fault_distant(), "img2": scenario_fault_closeup()},
    )

    decision = decide(context, mode="industrial")

    assert decision.tool == "compare_observations"
    assert decision.arguments["previous_image_id"] == "img1"
    assert decision.arguments["current_image_id"] == "img2"


def test_policy_is_deterministic_for_the_same_evidence(engine, industrial_profile):
    first = decide(_context(engine, industrial_profile, {"img1": scenario_fault_closeup()}))
    second = decide(_context(engine, industrial_profile, {"img1": scenario_fault_closeup()}))

    assert first.tool == second.tool
    assert first.arguments == second.arguments


def test_policy_actual_measurement_is_what_drives_the_decision(engine, industrial_profile):
    """Move only the pressure and watch the decision change with it."""
    normal = decide(
        _context(
            engine,
            industrial_profile,
            {"img1": render_industrial_panel(pressure_psi=30.0, warning="OFF", status="GREEN")},
        ),
        mode="industrial",
    )
    high = decide(
        _context(
            engine,
            industrial_profile,
            {"img1": render_industrial_panel(pressure_psi=95.0, warning="OFF", status="GREEN")},
        ),
        mode="industrial",
    )

    assert "No fault found" in normal.arguments["summary"]
    assert "Abnormal condition confirmed" in high.arguments["summary"]
    assert "above" in high.arguments["summary"]
