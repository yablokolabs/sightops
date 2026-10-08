"""The agentic inspection loop.

One ``run`` call drives an inspection forward by some number of steps and stops
in a state a human can understand. It is bounded four ways — steps, total tool
calls, reinspection rounds and a per-step timeout — because an agent that can
loop forever on a photograph is not a product.

Two brains plug into the same loop:

* **live mode** — the Nebius model chooses the next tool call, with the tool
  results fed back as ``role="tool"`` messages. If the provider fails, the run
  degrades to the deterministic policy and says so in the timeline rather than
  silently pretending to have reasoned.
* **demo mode** — :mod:`app.agent.policy` chooses, from the same measurements.
  Labelled ``DEMO MODE`` everywhere it appears.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field

import numpy as np

from app.agent import policy as demo_policy
from app.agent.prompts import build_user_turn, evidence_digest, system_prompt
from app.agent.state import IllegalTransition, transition
from app.agent.tools import ToolContext, ToolError, get_tool, tool_schemas
from app.config import Settings, get_settings
from app.models.schemas import (
    Assessment,
    Inspection,
    InspectionMode,
    InspectionState,
    Provenance,
    ReinspectionRequest,
    Severity,
    TimelineKind,
    ToolCallRecord,
    utcnow,
)
from app.providers.base import ModelProvider, ProviderError
from app.storage.repo import Repository
from app.vision.annotate import draw_analysis
from app.vision.engine import VisionEngine
from app.vision.profiles import get_profile


@dataclass
class RunResult:
    inspection_id: str
    steps: int = 0
    tool_calls: int = 0
    state: InspectionState = InspectionState.CREATED
    degraded: bool = False
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class InspectionAgent:
    def __init__(
        self,
        repo: Repository,
        engine: VisionEngine,
        provider: ModelProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.repo = repo
        self.engine = engine
        self.provider = provider
        self.settings = settings or get_settings()

    # -- public entry point -------------------------------------------------

    async def run(
        self, inspection_id: str, *, user_message: str | None = None
    ) -> RunResult:
        inspection = await self.repo.get_inspection(inspection_id)
        if inspection is None:
            raise KeyError(f"unknown inspection {inspection_id!r}")

        result = RunResult(inspection_id=inspection_id, state=inspection.state)

        if user_message:
            inspection.problem_statement = (
                f"{inspection.problem_statement}\n{user_message}".strip()
                if inspection.problem_statement
                else user_message
            )
            await self.repo.add_timeline(
                inspection_id,
                TimelineKind.USER_MESSAGE,
                "User message",
                user_message,
                state=inspection.state,
            )

        if not inspection.observations:
            await self.repo.add_timeline(
                inspection_id,
                TimelineKind.REASONING,
                "Nothing to inspect yet",
                "No image has been supplied for this inspection.",
                state=inspection.state,
            )
            await self.repo.update_inspection(inspection)
            result.state = inspection.state
            return result

        deterministic = await self._resolve_mode(inspection, result)

        try:
            await self._drive(inspection, result, deterministic=deterministic)
        except Exception as exc:  # noqa: BLE001 - surfaced, not swallowed
            inspection.error = f"{type(exc).__name__}: {exc}"
            self._force_state(inspection, InspectionState.FAILED)
            result.errors.append(inspection.error)
            await self.repo.add_timeline(
                inspection_id,
                TimelineKind.ERROR,
                "Investigation failed",
                inspection.error,
                state=inspection.state,
            )

        await self.repo.update_inspection(inspection)
        result.state = inspection.state
        result.steps = inspection.step_count
        result.tool_calls = inspection.tool_call_count
        return result

    # -- mode ---------------------------------------------------------------

    async def _resolve_mode(self, inspection: Inspection, result: RunResult) -> bool:
        if inspection.demo_mode:
            await self.repo.add_timeline(
                inspection.id,
                TimelineKind.REASONING,
                "DEMO MODE",
                (
                    "This run uses the deterministic evidence-driven policy, not a language "
                    "model. Every value it acts on was measured by OpenCV from the uploaded "
                    "images; the tool calls and measurements below are real."
                ),
                state=inspection.state,
            )
            return True
        if self.provider is None or not await self.provider.is_available():
            result.degraded = True
            await self.repo.add_timeline(
                inspection.id,
                TimelineKind.ERROR,
                "Live reasoning unavailable",
                (
                    "No language-model provider is configured, so this run continues with the "
                    "deterministic policy. Measurements are unaffected."
                ),
                state=inspection.state,
            )
            return True
        return False

    # -- the loop -----------------------------------------------------------

    async def _drive(
        self, inspection: Inspection, result: RunResult, *, deterministic: bool
    ) -> None:
        profile = get_profile(inspection.profile_id)
        images = {obs.image_id: await self._load_image(obs.image_id) for obs in inspection.observations}
        analyses = {
            obs.image_id: obs.analysis for obs in inspection.observations if obs.analysis is not None
        }
        ordered = [obs.image_id for obs in inspection.observations]

        context = ToolContext(
            engine=self.engine,
            profile=profile,
            images={k: v for k, v in images.items() if v is not None},
            analyses=dict(analyses),
            ordered_image_ids=[i for i in ordered if i in images and images[i] is not None],
        )
        if not context.ordered_image_ids:
            raise RuntimeError("no decodable images are attached to this inspection")

        messages: list[dict] = [{"role": "system", "content": system_prompt(inspection.mode)}]
        # Counted from the persisted trace so a re-run after the user uploads a
        # new photograph cannot restart the reinspection budget from zero.
        prior_calls = await self.repo.list_tool_calls(inspection.id)
        reinspection_rounds = sum(1 for c in prior_calls if c.tool == "request_new_view" and c.ok)

        steps = 0
        tool_calls = 0
        failed_tools: set[str] = set()
        tool_call_id: str | None = None
        while steps < self.settings.max_agent_steps and tool_calls < self.settings.max_tool_calls:
            steps += 1
            inspection.step_count += 1
            await self._ensure_reasoning(inspection)

            if deterministic:
                decision = demo_policy.decide(
                    context,
                    problem=inspection.problem_statement,
                    reinspection_rounds=reinspection_rounds,
                    max_reinspection_rounds=self.settings.max_reinspection_rounds,
                    incident_created=inspection.incident_id is not None,
                    approval_requested=bool(getattr(context, "approval_request", None)),
                    diagnosed=inspection.assessment is not None,
                    mode=inspection.mode.value,
                )
                if decision.tool in failed_tools:
                    await self.repo.add_timeline(
                        inspection.id,
                        TimelineKind.ERROR,
                        "Stopping: repeated tool failure",
                        (
                            f"{decision.tool} already failed in this run; the investigation is "
                            "stopping rather than repeating a call that cannot succeed."
                        ),
                        state=inspection.state,
                    )
                    break
                tool_name, arguments, rationale, source = (
                    decision.tool,
                    decision.arguments,
                    decision.rationale,
                    "policy",
                )
                await self.repo.add_timeline(
                    inspection.id,
                    TimelineKind.DECISION,
                    f"Decision: {tool_name}",
                    rationale,
                    state=inspection.state,
                    data={"tool": tool_name, "arguments": arguments, "policy": "deterministic_demo"},
                )
            else:
                turn = build_user_turn(
                    problem=inspection.problem_statement,
                    appliance=inspection.appliance,
                    digests=[evidence_digest(a) for a in context.analyses.values()],
                    pending_request=(
                        inspection.pending_request.instruction if inspection.pending_request else None
                    ),
                    step=steps,
                    max_steps=self.settings.max_agent_steps,
                )
                messages.append({"role": "user", "content": turn})
                try:
                    response = await asyncio.wait_for(
                        self.provider.generate(messages, tools=tool_schemas()),
                        timeout=self.settings.agent_step_timeout_seconds,
                    )
                except (ProviderError, asyncio.TimeoutError) as exc:
                    result.degraded = True
                    inspection.error = f"model step failed: {exc}"
                    await self.repo.add_timeline(
                        inspection.id,
                        TimelineKind.ERROR,
                        "Reasoning step failed",
                        f"{exc}. Continuing with the deterministic policy.",
                        state=inspection.state,
                    )
                    deterministic = True
                    steps -= 1
                    continue

                if not response.tool_calls:
                    # The model answered in prose instead of calling a tool. Record
                    # it as an inferred assessment and stop.
                    await self._record_prose(inspection, response.content, result)
                    break

                call = response.tool_calls[0]
                tool_name, arguments, source = call.name, call.arguments, "model"
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": [
                            {
                                "id": call.id,
                                "type": "function",
                                "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                            }
                        ],
                    }
                )
                await self.repo.add_timeline(
                    inspection.id,
                    TimelineKind.DECISION,
                    f"Decision: {tool_name}",
                    response.content.strip() or _summarise_arguments(arguments),
                    state=inspection.state,
                    data={
                        "tool": tool_name,
                        "arguments": arguments,
                        "model": response.model,
                        "usage": response.usage.total_tokens,
                    },
                )
                tool_call_id = call.id

            started = time.perf_counter()
            tool_calls += 1
            inspection.tool_call_count += 1
            ok = True
            error: str | None = None
            try:
                tool = get_tool(tool_name)
                validated = tool.validate(arguments)
                output = await asyncio.wait_for(
                    tool.run(context, validated), timeout=self.settings.agent_step_timeout_seconds
                )
            except (ToolError, KeyError, ValueError) as exc:
                ok, error, output = False, str(exc), {}
            except asyncio.TimeoutError:
                ok, error, output = False, f"tool {tool_name} timed out", {}
            except Exception as exc:  # noqa: BLE001
                ok, error, output = False, f"{type(exc).__name__}: {exc}", {}

            duration = (time.perf_counter() - started) * 1000.0
            await self.repo.add_tool_call(
                ToolCallRecord(
                    inspection_id=inspection.id,
                    step=steps,
                    tool=tool_name,
                    arguments=arguments,
                    ok=ok,
                    result=_truncate(output),
                    error=error,
                    duration_ms=round(duration, 2),
                    source=source,
                )
            )
            await self.repo.add_timeline(
                inspection.id,
                TimelineKind.TOOL_RESULT if ok else TimelineKind.ERROR,
                f"{tool_name} {'succeeded' if ok else 'failed'}",
                _result_summary(tool_name, output) if ok else (error or "unknown error"),
                state=inspection.state,
                data={"ok": ok, "duration_ms": round(duration, 2)},
            )

            if not deterministic:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id or f"call_{tool_calls}",
                        "content": json.dumps(
                            output if ok else {"error": error}, default=str
                        )[:6000],
                    }
                )

            if not ok:
                failed_tools.add(tool_name)
                continue

            await self._apply_outcome(inspection, context, tool_name, result)
            if tool_name in {"request_new_view", "ask_user", "request_human_approval"}:
                if tool_name == "request_new_view":
                    reinspection_rounds += 1
                break
            if inspection.state in {
                InspectionState.COMPLETED,
                InspectionState.AWAITING_APPROVAL,
                InspectionState.WAITING_FOR_USER,
            }:
                break

        inspection.updated_at = utcnow()
        await self.repo.update_inspection(inspection)
        await self._annotate_observations(inspection)

    # -- outcomes -----------------------------------------------------------

    async def _apply_outcome(
        self, inspection: Inspection, context: ToolContext, tool_name: str, result: RunResult
    ) -> None:
        if tool_name == "inspect_panel" and context.analyses:
            image_id, analysis = next(reversed(list(context.analyses.items())))
            await self.repo.update_observation_analysis(image_id, analysis)
            await self.repo.add_timeline(
                inspection.id,
                TimelineKind.OBSERVATION,
                "Measurements produced by OpenCV",
                f"{len(analysis.measurements)} components measured in {analysis.latency_ms:.0f} ms",
                state=inspection.state,
                data={
                    "image_id": image_id,
                    "opencv_version": analysis.opencv_version,
                    "quality": analysis.quality.model_dump(mode="json"),
                },
            )

        if tool_name == "request_new_view" and context.pending_request:
            self._goto(inspection, InspectionState.NEEDS_MORE_EVIDENCE)
            inspection.pending_request = ReinspectionRequest(**context.pending_request)
            self._goto(inspection, InspectionState.WAITING_FOR_USER)
            await self.repo.add_timeline(
                inspection.id,
                TimelineKind.REQUEST,
                "Better evidence requested",
                f"{inspection.pending_request.instruction} Reason: {inspection.pending_request.reason}",
                state=inspection.state,
                data=context.pending_request,
            )

        if tool_name == "ask_user" and context.question:
            self._goto(inspection, InspectionState.WAITING_FOR_USER)
            await self.repo.add_timeline(
                inspection.id,
                TimelineKind.REQUEST,
                "Question for the user",
                context.question["question"],
                state=inspection.state,
                data=context.question,
            )

        if tool_name == "record_diagnosis" and context.diagnosis:
            self._goto(inspection, InspectionState.DIAGNOSING)
            if self._needs_action(context, inspection):
                # There is still an incident to raise and an approval to ask
                # for, so the investigation continues from the proposal state.
                self._goto(inspection, InspectionState.ACTION_PROPOSED)
            else:
                inspection.outcome = context.diagnosis["summary"]
                self._goto(inspection, InspectionState.COMPLETED)
            inspection.assessment = Assessment(
                summary=context.diagnosis["summary"],
                confidence=float(context.diagnosis["confidence"]),
                needs_more_evidence=False,
                recommended_next_step=context.diagnosis.get("recommended_next_step") or None,
                user_message=context.diagnosis.get("user_message", ""),
            )
            await self.repo.add_timeline(
                inspection.id,
                TimelineKind.REASONING,
                "Assessment recorded (model/policy interpretation)",
                context.diagnosis["summary"],
                state=inspection.state,
                data={
                    "confidence": context.diagnosis["confidence"],
                    "provenance": Provenance.INFERRED.value,
                    "user_message": context.diagnosis.get("user_message", ""),
                },
            )

        if tool_name == "create_incident" and context.incident_request:
            payload = context.incident_request
            from app.models.schemas import Incident, IncidentStatus

            incident = Incident(
                id=uuid.uuid4().hex,
                inspection_id=inspection.id,
                title=payload["title"],
                summary=payload["summary"],
                severity=Severity(payload["severity"].lower()),
                status=IncidentStatus.OPEN,
                evidence_image_ids=[o.image_id for o in inspection.observations],
                measurements=[
                    m for a in context.analyses.values() for m in a.measurements
                ],
                proposed_action=payload["proposed_action"],
                approval_required=bool(payload.get("requires_approval", True)),
            )
            await self.repo.create_incident(incident)
            inspection.incident_id = incident.id
            self._goto(inspection, InspectionState.ACTION_PROPOSED)
            await self.repo.add_timeline(
                inspection.id,
                TimelineKind.INCIDENT,
                "Incident created",
                f"{incident.title} — severity {incident.severity.value}. "
                f"Proposed action is SIMULATED and requires approval.",
                state=inspection.state,
                data={"incident_id": incident.id},
            )

        if tool_name == "request_human_approval" and context.approval_request:
            self._goto(inspection, InspectionState.ACTION_PROPOSED)
            self._goto(inspection, InspectionState.AWAITING_APPROVAL)
            if inspection.incident_id:
                incident = await self.repo.get_incident(inspection.incident_id)
                if incident is not None:
                    from app.models.schemas import IncidentStatus

                    incident.status = IncidentStatus.AWAITING_APPROVAL
                    incident.updated_at = utcnow()
                    await self.repo.update_incident(incident)
            await self.repo.add_timeline(
                inspection.id,
                TimelineKind.APPROVAL,
                "Human approval required",
                f"{context.approval_request['action']} — {context.approval_request['rationale']}",
                state=inspection.state,
                data=context.approval_request,
            )

    async def _record_prose(self, inspection: Inspection, content: str, result: RunResult) -> None:
        text = (content or "").strip()
        self._goto(inspection, InspectionState.DIAGNOSING)
        inspection.assessment = Assessment(
            summary=text[:1500] or "The model returned no content.",
            confidence=0.5,
            needs_more_evidence=False,
            user_message=text[:1500],
        )
        await self.repo.add_timeline(
            inspection.id,
            TimelineKind.REASONING,
            "Model response (inferred, no tool call)",
            text[:1500] or "(empty)",
            state=inspection.state,
            data={"provenance": Provenance.INFERRED.value},
        )
        result.messages.append(text[:1500])

    # -- state plumbing -----------------------------------------------------

    def _goto(self, inspection: Inspection, target: InspectionState) -> None:
        """Move to ``target`` along the shortest legal path in the state table.

        Routing through :func:`_find_path` instead of hand-written hop lists
        means the loop cannot drift from the documented transitions.
        """
        if inspection.state == target:
            return
        path = _find_path(inspection.state, target)
        if path is None:
            raise IllegalTransition(inspection.state, target)
        for hop in path:
            inspection.state = transition(inspection.state, hop)

    def _force_state(self, inspection: Inspection, target: InspectionState) -> None:
        try:
            self._goto(inspection, target)
        except IllegalTransition:
            inspection.state = target

    async def _ensure_reasoning(self, inspection: Inspection) -> None:
        if inspection.state == InspectionState.REASONING:
            return
        path = {
            InspectionState.CREATED: [InspectionState.OBSERVING, InspectionState.ANALYZING],
            InspectionState.OBSERVING: [InspectionState.ANALYZING],
            InspectionState.ANALYZING: [],
            InspectionState.REOBSERVING: [InspectionState.ANALYZING],
            InspectionState.WAITING_FOR_USER: [InspectionState.REOBSERVING, InspectionState.ANALYZING],
            InspectionState.NEEDS_MORE_EVIDENCE: [InspectionState.REOBSERVING, InspectionState.ANALYZING],
            InspectionState.DIAGNOSING: [],
            InspectionState.ACTION_PROPOSED: [],
            InspectionState.FAILED: [InspectionState.OBSERVING, InspectionState.ANALYZING],
        }.get(inspection.state, [])
        for hop in path:
            inspection.state = transition(inspection.state, hop)
        inspection.state = transition(inspection.state, InspectionState.REASONING)

    @staticmethod
    def _needs_action(context: ToolContext, inspection: Inspection) -> bool:
        """Whether the measured evidence still warrants an incident and approval.

        Home mode is advice-only: no incident is raised for a dishwasher. In
        industrial mode an abnormal measurement must be carried through to a
        recorded incident and an explicit approval gate.
        """
        from app.models.schemas import GaugeState

        if inspection.mode is not InspectionMode.INDUSTRIAL:
            return False
        analysis = context.analyses.get(context.ordered_image_ids[-1])
        if analysis is None:
            return False
        for measurement in analysis.measurements:
            if measurement.component_type == "analog_gauge" and measurement.state == GaugeState.HIGH.value:
                return True
            if measurement.component_type == "indicator" and measurement.state in {
                "RED",
                "AMBER",
            }:
                return True
        return False

    # -- helpers ------------------------------------------------------------

    async def _load_image(self, image_id: str) -> np.ndarray | None:
        from app.storage.evidence import LocalEvidenceStorage

        record = await self.repo.get_image(image_id)
        if record is None:
            return None
        storage = LocalEvidenceStorage(self.settings.evidence_dir)
        try:
            data = storage.get(record["stored_path"])
        except (FileNotFoundError, ValueError):
            return None
        try:
            return self.engine.decode(data)
        except Exception:  # noqa: BLE001
            return None

    async def _annotate_observations(self, inspection: Inspection) -> None:
        """Render annotated evidence once per observation."""
        from app.storage.evidence import LocalEvidenceStorage

        storage = LocalEvidenceStorage(self.settings.evidence_dir)
        for observation in await self.repo.list_observations(inspection.id):
            record = await self.repo.get_image(observation.image_id)
            if record is None or record["annotated_path"] or observation.analysis is None:
                continue
            image = await self._load_image(observation.image_id)
            if image is None:
                continue
            annotated = draw_analysis(image, observation.analysis)
            key = storage.put(
                inspection.id, f"{observation.image_id}-annotated", "png",
                _encode_png(annotated),
            )
            await self.repo.set_annotated_path(observation.image_id, key)


def _encode_png(image: np.ndarray) -> bytes:
    from app.vision.annotate import encode_png

    return encode_png(image)


def _summarise_arguments(arguments: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in arguments.items()) or "(no arguments)"


def _truncate(output: dict, limit: int = 4000) -> dict:
    encoded = json.dumps(output, default=str)
    if len(encoded) <= limit:
        return output
    return {"truncated": True, "preview": encoded[:limit]}


def _result_summary(tool_name: str, output: dict) -> str:
    if tool_name == "inspect_panel":
        measurements = output.get("measurements") or []
        return f"{len(measurements)} measurements: " + ", ".join(
            f"{m['component_id']}={m.get('state') or m.get('value')}" for m in measurements
        )
    if tool_name == "read_gauge":
        if output.get("value") is None:
            return f"{output.get('region_id')}: could not be read ({'; '.join(output.get('notes') or [])})"
        return (
            f"{output.get('region_id')}: {output.get('value')} {output.get('unit') or ''} "
            f"(confidence {output.get('confidence')})"
        )
    if tool_name == "detect_indicator":
        return f"{output.get('region_id')}: {output.get('state')} (confidence {output.get('confidence')})"
    if tool_name == "compare_observations":
        return f"{len(output.get('changes') or [])} change(s) recorded"
    if tool_name == "request_new_view":
        return f"Asked for {output.get('target_region')}: {output.get('instruction')}"
    return json.dumps(output, default=str)[:400]


def _find_path(
    start: InspectionState, target: InspectionState, *, max_depth: int = 6
) -> list[InspectionState] | None:
    """Breadth-first search over the state table for the shortest route."""
    from app.agent.state import TRANSITIONS

    if start == target:
        return []
    queue: list[list[InspectionState]] = [[start]]
    seen = {start}
    while queue:
        path = queue.pop(0)
        if len(path) > max_depth:
            continue
        for nxt in sorted(TRANSITIONS.get(path[-1], set()), key=lambda s: s.value):
            if nxt in seen:
                continue
            if nxt == target:
                return path[1:] + [nxt]
            seen.add(nxt)
            queue.append(path + [nxt])
    return None
