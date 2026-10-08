"""Typed agent tools.

Each tool is a small class with a Pydantic argument model, a JSON schema handed
to the model, and an async ``run`` that returns a JSON-serialisable dict. Tool
arguments are validated from untrusted model output before anything executes,
which is what makes it safe to give a language model a list of actions.

Tools return *evidence*, never decisions: ``read_gauge`` returns a measurement,
and the choice of what to do next stays with the agent. The one exception is
``request_new_view``, which records a request for the human and therefore has a
side effect the API must surface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

import numpy as np
from pydantic import BaseModel, ValidationError

from app.vision.change import compare_analyses, pixel_difference
from app.vision.engine import VisionEngine
from app.vision.profiles import EquipmentProfile
from app.vision.regions import detect_panel


class ToolError(RuntimeError):
    """Raised for a tool that cannot run — bad arguments or missing evidence."""


class ToolContext:
    """Everything a tool may touch. Deliberately small."""

    def __init__(
        self,
        *,
        engine: VisionEngine,
        profile: EquipmentProfile,
        images: dict[str, np.ndarray],
        analyses: dict[str, Any],
        ordered_image_ids: list[str],
    ) -> None:
        self.engine = engine
        self.profile = profile
        self.images = images
        self.analyses = analyses
        self.ordered_image_ids = ordered_image_ids
        # Outputs written by the terminal tools, read back by the agent loop.
        #: Set by ``request_new_view`` so the loop can persist the request.
        self.pending_request: dict[str, Any] | None = None
        self.diagnosis: dict[str, Any] | None = None
        self.incident_request: dict[str, Any] | None = None
        self.approval_request: dict[str, Any] | None = None
        self.question: dict[str, Any] | None = None

    def resolve_image(self, image_id: str | None) -> tuple[str, np.ndarray]:
        if not self.ordered_image_ids:
            raise ToolError("this inspection has no images yet")
        if image_id is None:
            image_id = self.ordered_image_ids[-1]
        if image_id not in self.images:
            raise ToolError(
                f"unknown image_id {image_id!r}; available: {', '.join(self.ordered_image_ids)}"
            )
        return image_id, self.images[image_id]

    def analysis_of(self, image_id: str) -> Any:
        analysis = self.analyses.get(image_id)
        if analysis is None:
            raise ToolError(f"image {image_id!r} has not been analysed yet")
        return analysis


class Tool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    Arguments: ClassVar[type[BaseModel]]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.Arguments.model_json_schema(),
            },
        }

    def validate(self, arguments: dict[str, Any]) -> BaseModel:
        try:
            return self.Arguments.model_validate(arguments or {})
        except ValidationError as exc:
            raise ToolError(f"invalid arguments for {self.name}: {exc.errors()[:3]}") from exc

    @abstractmethod
    async def run(self, context: ToolContext, arguments: BaseModel) -> dict[str, Any]: ...


# --------------------------------------------------------------------------
# vision tools
# --------------------------------------------------------------------------


class InspectPanelArgs(BaseModel):
    image_id: str | None = None
    rectify: bool = False


class InspectPanelTool(Tool):
    name = "inspect_panel"
    description = (
        "Measure every configured component on the equipment panel in one pass, and locate the "
        "panel itself. Use this first, and again after a new image arrives."
    )
    Arguments = InspectPanelArgs

    async def run(self, context: ToolContext, arguments: InspectPanelArgs) -> dict[str, Any]:
        image_id, image = context.resolve_image(arguments.image_id)
        analysis = context.engine.analyze(
            image, image_id=image_id, profile=context.profile, rectify=arguments.rectify
        )
        context.analyses[image_id] = analysis
        panel = detect_panel(image)
        return {
            "image_id": image_id,
            "profile_id": analysis.profile_id,
            "panel": (
                {
                    "box": panel.normalised_box(image.shape[1], image.shape[0]),
                    "confidence": round(panel.confidence, 4),
                    "area_ratio": round(panel.area_ratio, 4),
                    "source": "detected",
                }
                if panel
                else None
            ),
            "quality": analysis.quality.model_dump(mode="json"),
            "measurements": [m.model_dump(mode="json") for m in analysis.measurements],
            "regions": [
                {"region_id": r.region_id, "kind": r.kind, "label": r.label, "box": list(r.box)}
                for r in analysis.regions
            ],
        }


class InspectRegionArgs(BaseModel):
    region_id: str
    image_id: str | None = None


class InspectRegionTool(Tool):
    name = "inspect_region"
    description = (
        "Re-measure one named component region (for example a single indicator or gauge) and "
        "report its quality separately from the rest of the panel."
    )
    Arguments = InspectRegionArgs

    async def run(self, context: ToolContext, arguments: InspectRegionArgs) -> dict[str, Any]:
        if context.profile.region(arguments.region_id) is None:
            raise ToolError(
                f"unknown region_id {arguments.region_id!r}; available: "
                f"{', '.join(r.region_id for r in context.profile.regions)}"
            )
        image_id, image = context.resolve_image(arguments.image_id)
        region = context.engine.analyze_region(
            image,
            image_id=image_id,
            profile=context.profile,
            region_id=arguments.region_id,
        )
        return {
            "image_id": image_id,
            "region_id": region.region_id,
            "kind": region.kind,
            "box": list(region.box),
            "quality": region.quality.model_dump(mode="json") if region.quality else None,
            "measurements": [m.model_dump(mode="json") for m in region.measurements],
        }


class ReadGaugeArgs(BaseModel):
    region_id: str
    image_id: str | None = None


class ReadGaugeTool(Tool):
    name = "read_gauge"
    description = (
        "Attempt to read an analog gauge. Returns the value, unit, confidence and the criteria "
        "behind that confidence. Returns state UNKNOWN with no value when the needle cannot be "
        "measured reliably — that is a valid result, not an error."
    )
    Arguments = ReadGaugeArgs

    async def run(self, context: ToolContext, arguments: ReadGaugeArgs) -> dict[str, Any]:
        spec = context.profile.region(arguments.region_id)
        if spec is None or spec.kind != "gauge":
            raise ToolError(
                f"{arguments.region_id!r} is not a gauge region in profile "
                f"{context.profile.profile_id}"
            )
        image_id, image = context.resolve_image(arguments.image_id)
        region = context.engine.analyze_region(
            image, image_id=image_id, profile=context.profile, region_id=spec.region_id
        )
        measurement = region.measurements[0]
        return {
            "image_id": image_id,
            "region_id": spec.region_id,
            "readable": measurement.value is not None,
            "value": measurement.value,
            "unit": measurement.unit,
            "state": measurement.state,
            "warn_above": spec.warn_above,
            "confidence": measurement.confidence,
            "requires_reinspection": measurement.requires_reinspection,
            "notes": measurement.notes,
            "method": measurement.method,
            "details": measurement.details,
        }


class DetectIndicatorArgs(BaseModel):
    region_id: str
    image_id: str | None = None


class DetectIndicatorTool(Tool):
    name = "detect_indicator"
    description = (
        "Classify a status indicator or warning lamp as RED, GREEN, AMBER, BLUE, WHITE, OFF or "
        "UNKNOWN, with the HSV criteria behind the decision."
    )
    Arguments = DetectIndicatorArgs

    async def run(self, context: ToolContext, arguments: DetectIndicatorArgs) -> dict[str, Any]:
        spec = context.profile.region(arguments.region_id)
        if spec is None or spec.kind != "indicator":
            raise ToolError(f"{arguments.region_id!r} is not an indicator region")
        image_id, image = context.resolve_image(arguments.image_id)
        region = context.engine.analyze_region(
            image, image_id=image_id, profile=context.profile, region_id=spec.region_id
        )
        measurement = region.measurements[0]
        return {
            "image_id": image_id,
            "region_id": spec.region_id,
            "state": measurement.state,
            "confidence": measurement.confidence,
            "method": measurement.method,
            "requires_reinspection": measurement.requires_reinspection,
            "notes": measurement.notes,
            "details": measurement.details,
        }


class CheckQualityArgs(BaseModel):
    image_id: str | None = None
    region_id: str | None = None


class CheckQualityTool(Tool):
    name = "check_image_quality"
    description = (
        "Score an image, or one region of it, for blur, exposure and resolution, and report "
        "whether a new view is needed and why."
    )
    Arguments = CheckQualityArgs

    async def run(self, context: ToolContext, arguments: CheckQualityArgs) -> dict[str, Any]:
        if arguments.region_id is not None and context.profile.region(arguments.region_id) is None:
            raise ToolError(f"unknown region_id {arguments.region_id!r}")
        image_id, image = context.resolve_image(arguments.image_id)
        quality = context.engine.check_quality(image, arguments.region_id, context.profile)
        return {"image_id": image_id, "quality": quality.model_dump(mode="json")}


class CompareObservationsArgs(BaseModel):
    previous_image_id: str
    current_image_id: str


class CompareObservationsTool(Tool):
    name = "compare_observations"
    description = (
        "Compare two observations component by component and report what changed, with a severity "
        "for each change. Use this whenever the user supplies an additional image."
    )
    Arguments = CompareObservationsArgs

    async def run(self, context: ToolContext, arguments: CompareObservationsArgs) -> dict[str, Any]:
        previous = context.analysis_of(arguments.previous_image_id)
        current = context.analysis_of(arguments.current_image_id)
        pixel_mean, _ = pixel_difference(
            context.images[arguments.previous_image_id], context.images[arguments.current_image_id]
        )
        report = compare_analyses(previous, current, pixel_mean_abs_diff=pixel_mean)
        return report.model_dump(mode="json")


class RequestNewViewArgs(BaseModel):
    target_region: str
    instruction: str
    reason: str


class RequestNewViewTool(Tool):
    name = "request_new_view"
    description = (
        "Ask the user for a better photograph when the current evidence is not good enough. "
        "Always state which part of the equipment to capture and why."
    )
    Arguments = RequestNewViewArgs

    async def run(self, context: ToolContext, arguments: RequestNewViewArgs) -> dict[str, Any]:
        context.pending_request = {
            "target_region": arguments.target_region,
            "instruction": arguments.instruction,
            "reason": arguments.reason,
        }
        return {"recorded": True, **context.pending_request}


class RecordDiagnosisArgs(BaseModel):
    summary: str
    confidence: float
    recommended_next_step: str = ""
    user_message: str = ""


class RecordDiagnosisTool(Tool):
    name = "record_diagnosis"
    description = (
        "Record the current conclusion, how confident you are in it, and what the user should do "
        "next. Call this when the evidence supports a conclusion, or to state that the evidence "
        "does not."
    )
    Arguments = RecordDiagnosisArgs

    async def run(self, context: ToolContext, arguments: RecordDiagnosisArgs) -> dict[str, Any]:
        context.diagnosis = arguments.model_dump()
        return {"recorded": True, **arguments.model_dump()}


class CreateIncidentArgs(BaseModel):
    title: str
    summary: str
    severity: str
    proposed_action: str
    requires_approval: bool = True


class CreateIncidentTool(Tool):
    name = "create_incident"
    description = (
        "Raise a maintenance incident from the evidence gathered so far. Any proposed remediation "
        "is simulated and requires explicit human approval before it is recorded as approved."
    )
    Arguments = CreateIncidentArgs

    async def run(self, context: ToolContext, arguments: CreateIncidentArgs) -> dict[str, Any]:
        from app.models.schemas import Severity

        if arguments.severity.lower() not in {s.value for s in Severity}:
            raise ToolError(
                f"severity must be one of {', '.join(s.value for s in Severity)}; "
                f"got {arguments.severity!r}"
            )
        payload = arguments.model_dump()
        context.incident_request = payload
        return {"recorded": True, **payload}


class RequestHumanApprovalArgs(BaseModel):
    action: str
    rationale: str
    equipment_impact: str


class RequestHumanApprovalTool(Tool):
    name = "request_human_approval"
    description = (
        "Escalate a consequential action for explicit human approval. SightOps never controls real "
        "machinery; every remediation in this system is simulated and cannot proceed without this "
        "approval."
    )
    Arguments = RequestHumanApprovalArgs

    async def run(self, context: ToolContext, arguments: RequestHumanApprovalArgs) -> dict[str, Any]:
        payload = arguments.model_dump()
        context.approval_request = payload
        return {"recorded": True, "approval_required": True, **payload}


class AskUserArgs(BaseModel):
    question: str
    options: list[str] = []


class AskUserTool(Tool):
    name = "ask_user"
    description = (
        "Ask the user a question that visual evidence alone cannot answer, such as what a display "
        "said or what a sound was. Use simple, non-technical wording in home mode."
    )
    Arguments = AskUserArgs

    async def run(self, context: ToolContext, arguments: AskUserArgs) -> dict[str, Any]:
        context.question = arguments.model_dump()
        return {"recorded": True, **arguments.model_dump()}


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------

ALL_TOOLS: list[Tool] = [
    InspectPanelTool(),
    InspectRegionTool(),
    ReadGaugeTool(),
    DetectIndicatorTool(),
    CheckQualityTool(),
    CompareObservationsTool(),
    RequestNewViewTool(),
    RecordDiagnosisTool(),
    CreateIncidentTool(),
    RequestHumanApprovalTool(),
    AskUserTool(),
]

REGISTRY: dict[str, Tool] = {tool.name: tool for tool in ALL_TOOLS}


def tool_schemas() -> list[dict[str, Any]]:
    return [tool.schema() for tool in ALL_TOOLS]


def get_tool(name: str) -> Tool:
    try:
        return REGISTRY[name]
    except KeyError as exc:
        raise ToolError(
            f"unknown tool {name!r}; available: {', '.join(sorted(REGISTRY))}"
        ) from exc
