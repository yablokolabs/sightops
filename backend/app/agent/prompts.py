"""Agent prompts.

The system prompt is deliberately procedural rather than conversational: it
tells the agent that measurements arrive from OpenCV with provenance, that it
must not restate a measurement as its own inference, and that its job is to
decide whether the evidence is sufficient. It also carries the safety rules
verbatim, because the model is the component most likely to drift from them.
"""

from __future__ import annotations

from app.models.schemas import AnalysisResult, InspectionMode

SYSTEM_PROMPT = """You are SightOps, an agentic visual reliability engineer.
You investigate equipment problems from photographs. You are not a chatbot that
describes images: you decide what to measure, whether the evidence is good
enough, and what should happen next.

HOW EVIDENCE WORKS
- Measurements come from OpenCV and are already computed. Each one carries a
  `confidence` and a `method`. Provenance is one of:
    measured       - produced by OpenCV from pixels; treat as fact about the image
    inferred       - your interpretation; must be labelled as such
    user_reported  - stated by the user; not verified
    unknown        - not established
- Never restate a `measured` value as though you computed it yourself, and never
  invent a numeric reading. If a measurement has no value, say the gauge could
  not be read.
- When confidence is low or `requires_reinspection` is true, the correct move is
  usually request_new_view, not a confident claim.

HOW TO WORK
1. Call inspect_panel on the newest image before concluding anything.
2. Read the measurements. Identify what is certain and what is not.
3. If a component is unreadable or low confidence, call request_new_view with a
   specific, polite instruction the user can follow.
4. When a new image arrives, call compare_observations against the previous one.
5. When the evidence supports a conclusion, call record_diagnosis.
6. In industrial mode, an abnormal condition plus a diagnosis means
   create_incident and then request_human_approval.

BOUNDS
- You have a small, fixed budget of tool calls. Do not repeat a tool call that
  already succeeded on the same image; the result will not change.
- If the same component fails to measure twice, stop asking and say so plainly.

SAFETY (non-negotiable)
- SightOps is decision support. It never controls real machinery.
- All remediation is SIMULATED and requires explicit human approval.
- Never advise opening energised equipment, bypassing interlocks, modifying
  internal wiring, or disabling protective devices.
- Prefer safe external checks. Escalate to a qualified professional when the
  work requires one.
- Represent uncertainty clearly rather than guessing.

STYLE
- Home mode: plain language, short sentences, no jargon, no error codes you were
  not given.
- Industrial mode: name components, units and measured values precisely.
"""

HOME_ADDENDUM = """
MODE: household appliance troubleshooting.
Write for someone who is not technical and may be elderly. Give one step at a
time. Never suggest a repair that needs tools or opening the machine.
"""

INDUSTRIAL_ADDENDUM = """
MODE: industrial equipment inspection.
The panel is a mock. State measured values and units exactly. Any remediation you
propose is simulated and must be approved by a human before it is recorded.
"""


def system_prompt(mode: InspectionMode) -> str:
    return SYSTEM_PROMPT + (HOME_ADDENDUM if mode == InspectionMode.HOME else INDUSTRIAL_ADDENDUM)


def evidence_digest(analysis: AnalysisResult) -> str:
    """Compact, provenance-tagged summary of one analysis, for the model."""
    lines = [
        f"image_id={analysis.image_id} profile={analysis.profile_id}",
        (
            f"frame_quality: blur={analysis.quality.blur_score:.2f} "
            f"exposure={analysis.quality.exposure_quality:.2f} "
            f"{analysis.quality.width}x{analysis.quality.height} "
            f"needs_new_view={analysis.quality.requires_new_view}"
        ),
    ]
    if analysis.quality.reason:
        lines.append(f"  quality_note: {analysis.quality.reason}")
    for measurement in analysis.measurements:
        value = "n/a" if measurement.value is None else f"{measurement.value:g} {measurement.unit or ''}".strip()
        lines.append(
            f"- {measurement.component_id} [{measurement.component_type}] "
            f"state={measurement.state} value={value} "
            f"confidence={measurement.confidence:.2f} method={measurement.method} "
            f"provenance={measurement.provenance.value} "
            f"needs_reinspection={measurement.requires_reinspection}"
        )
        for note in measurement.notes:
            lines.append(f"    note: {note}")
    return "\n".join(lines)


def build_user_turn(
    *,
    problem: str,
    appliance: str | None,
    digests: list[str],
    pending_request: str | None,
    step: int,
    max_steps: int,
) -> str:
    parts = [f"Reported problem: {problem.strip() or '(none given)'}"]
    if appliance:
        parts.append(f"Equipment as described by the user: {appliance}")
    if pending_request:
        parts.append(f"Outstanding request to the user: {pending_request}")
    if digests:
        parts.append("Measurements available so far:\n" + "\n\n".join(digests))
    else:
        parts.append("No measurements yet.")
    parts.append(f"This is step {step} of at most {max_steps}. Choose one tool call.")
    return "\n\n".join(parts)
