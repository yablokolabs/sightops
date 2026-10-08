"""Deterministic demonstration policy.

This is the brain used when an inspection runs in **demo mode**. It is a real
policy in the reinforcement-learning sense — it reads the measurements OpenCV
produced and selects the next action from them — but it is hand-written rather
than learned, so a demonstration is reproducible and costs no API calls.

It is *not* a replay of canned results: every value it acts on comes from the
vision engine, and the same policy on a healthy panel produces a completely
different trace from the same policy on a faulty one. ``tests/test_policy.py``
asserts exactly that.

The mode is labelled in the UI and in every timeline entry it produces, so
nothing here is ever presented as model reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agent.tools import ToolContext
from app.models.schemas import GaugeState, IndicatorState

#: Indicator states that mean "something is wrong" on a status lamp.
ABNORMAL_INDICATORS = {IndicatorState.RED.value, IndicatorState.AMBER.value}
#: On a *run status* lamp, OFF while the machine should be running is abnormal.
ABNORMAL_STATUS = {IndicatorState.RED.value, IndicatorState.AMBER.value, IndicatorState.OFF.value}


@dataclass
class Decision:
    tool: str
    arguments: dict[str, Any]
    rationale: str


def _latest(context: ToolContext) -> tuple[str, Any]:
    image_id = context.ordered_image_ids[-1]
    return image_id, context.analyses.get(image_id)


def _unreadable(analysis) -> list[str]:
    return [
        m.component_id
        for m in analysis.measurements
        if m.value is None and m.component_type == "analog_gauge"
    ]


def _low_confidence(analysis) -> list[str]:
    """Components the vision engine itself judged unfit to draw conclusions from.

    The policy defers to ``requires_reinspection`` rather than re-deciding with
    its own threshold: the vision layer already weighed blur, exposure, coverage
    and peak shape, and duplicating that judgement here is how the two layers
    would eventually disagree.
    """
    return [m.component_id for m in analysis.measurements if m.requires_reinspection]


def decide(
    context: ToolContext,
    *,
    problem: str = "",
    reinspection_rounds: int = 0,
    max_reinspection_rounds: int = 2,
    incident_created: bool = False,
    approval_requested: bool = False,
    diagnosed: bool = False,
    mode: str = "industrial",
) -> Decision:
    """Choose the next tool call from the measured evidence."""
    if not context.analyses:
        return Decision(
            tool="inspect_panel",
            arguments={"image_id": context.ordered_image_ids[-1]},
            rationale="no measurements exist yet, so measure the panel first",
        )

    image_id, analysis = _latest(context)
    if analysis is None:
        return Decision(
            tool="inspect_panel",
            arguments={"image_id": image_id},
            rationale="the newest observation has not been analysed yet",
        )

    # 1. Evidence quality gate. This is the defining behaviour of SightOps: a
    #    component that could not be measured reliably is investigated before
    #    any conclusion is drawn.
    unreadable = _unreadable(analysis)
    low = _low_confidence(analysis)
    if (unreadable or low) and reinspection_rounds < max_reinspection_rounds:
        target = (unreadable or low)[0]
        quality = next(
            (r.quality for r in analysis.regions if r.region_id == target), analysis.quality
        )
        reason = (quality.reason if quality and quality.reason else None) or (
            f"{target} was measured with low confidence"
        )
        return Decision(
            tool="request_new_view",
            arguments={
                "target_region": target,
                "instruction": _instruction_for(target, mode),
                "reason": reason,
            },
            rationale=(
                f"{target} is not measured well enough to draw a conclusion "
                f"({', '.join(unreadable + low)[:120]}); ask for a better photograph"
            ),
        )

    # 2. A second observation exists: state what changed before interpreting it.
    if len(context.ordered_image_ids) >= 2 and not getattr(context, "_compared", False):
        previous = context.ordered_image_ids[-2]
        if previous in context.analyses:
            context._compared = True  # type: ignore[attr-defined]
            return Decision(
                tool="compare_observations",
                arguments={"previous_image_id": previous, "current_image_id": image_id},
                rationale="a new observation arrived, so diff it against the previous one",
            )

    # 3. Interpret the evidence.
    gauge = next((m for m in analysis.measurements if m.component_type == "analog_gauge"), None)
    warning = next(
        (
            m
            for m in analysis.measurements
            if m.component_type == "indicator" and "warning" in m.component_id
        ),
        None,
    )
    abnormal_reasons: list[str] = []
    if gauge is not None and gauge.state == GaugeState.HIGH.value and gauge.value is not None:
        abnormal_reasons.append(
            f"{gauge.component_id} reads {gauge.value:g} {gauge.unit or ''}, above the "
            f"{gauge.details.get('scale', {}).get('warn_above')} {gauge.unit or ''} limit"
        )
    if warning is not None and warning.state in ABNORMAL_INDICATORS:
        abnormal_reasons.append(f"{warning.component_id} is lit {warning.state}")

    if abnormal_reasons and not diagnosed:
        return Decision(
            tool="record_diagnosis",
            arguments={
                "summary": "Abnormal condition confirmed: " + "; ".join(abnormal_reasons),
                "confidence": round(
                    min(
                        [m.confidence for m in (gauge, warning) if m is not None] or [0.5]
                    ),
                    3,
                ),
                "recommended_next_step": (
                    "Raise an incident and request human approval before any change is made."
                ),
                "user_message": _industrial_message(abnormal_reasons),
            },
            rationale="measured evidence shows an abnormal condition",
        )

    if abnormal_reasons and diagnosed and not incident_created and mode == "industrial":
        return Decision(
            tool="create_incident",
            arguments={
                "title": f"Abnormal condition on {analysis.profile_id}",
                "summary": "; ".join(abnormal_reasons),
                "severity": "high",
                "proposed_action": (
                    "Simulated remediation: reduce pump discharge pressure and re-verify the "
                    "warning indicator. No plant equipment is connected."
                ),
                "requires_approval": True,
            },
            rationale="the diagnosis is recorded, so raise the incident for tracking",
        )

    if abnormal_reasons and incident_created and not approval_requested and mode == "industrial":
        return Decision(
            tool="request_human_approval",
            arguments={
                "action": "Execute simulated remediation for the recorded incident",
                "rationale": "; ".join(abnormal_reasons),
                "equipment_impact": (
                    "None. This demonstrator is a mock panel with no connection to plant "
                    "equipment; the action is recorded, not executed."
                ),
            },
            rationale="a consequential action requires explicit human approval",
        )

    if not diagnosed:
        healthy = "all measured components are within their configured normal ranges"
        return Decision(
            tool="record_diagnosis",
            arguments={
                "summary": f"No fault found: {healthy}.",
                "confidence": round(
                    min((m.confidence for m in analysis.measurements), default=0.5), 3
                ),
                "recommended_next_step": (
                    "No action needed. Re-inspect if the behaviour changes."
                ),
                "user_message": _healthy_message(analysis, mode),
            },
            rationale="every component measured cleanly and within range",
        )

    return Decision(
        tool="record_diagnosis",
        arguments={
            "summary": "Investigation complete; the recorded conclusion stands.",
            "confidence": 0.6,
            "recommended_next_step": "Review the incident and approve or reject the action.",
            "user_message": "I have recorded everything I found. You can review it above.",
        },
        rationale="the investigation has reached its end state",
    )


def _instruction_for(target: str, mode: str) -> str:
    if mode == "home":
        return (
            f"Please take one more photo of the {target.replace('_', ' ')}. Hold the phone "
            "about 20 cm away, keep it straight rather than at an angle, and avoid casting a "
            "shadow or a reflection over it."
        )
    return (
        f"Re-image {target} square-on, filling most of the frame, with diffuse light and no "
        "specular reflection across the dial or lamp face."
    )


def _industrial_message(reasons: list[str]) -> str:
    return (
        "The panel is showing an abnormal condition: "
        + "; ".join(reasons)
        + ". I have recorded the evidence. No equipment has been touched — any change needs your "
        "explicit approval, and this panel is a mock."
    )


def _healthy_message(analysis, mode: str) -> str:
    if mode == "home":
        return (
            "Everything I could see looks normal. If the machine is still not working, tell me "
            "what it does instead, and I will look at something else."
        )
    summary = ", ".join(
        f"{m.component_id}={m.state if m.value is None else m.value}"
        for m in analysis.measurements
    )
    return f"All measured components are within range ({summary}). No action required."
