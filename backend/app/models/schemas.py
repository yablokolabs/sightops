"""Typed contracts shared by the API, vision engine, agent and storage layers.

Two ideas run through these models:

* **Provenance.** Every finding records how it was obtained — measured by
  OpenCV, inferred by a language model, reported by the user, or unknown. The
  UI is required to distinguish these, so the distinction lives in the type.
* **Confidence carries a reason.** A confidence number without the criteria
  behind it is not auditable, so measurements that can be uncertain also carry
  ``method`` (how it was measured) and ``requires_reinspection`` (the vision
  engine's own view of whether the evidence is good enough).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Provenance(str, Enum):
    """Where a finding came from."""

    MEASURED = "measured"
    INFERRED = "inferred"
    USER_REPORTED = "user_reported"
    UNKNOWN = "unknown"


class InspectionMode(str, Enum):
    HOME = "home"
    INDUSTRIAL = "industrial"


class InspectionState(str, Enum):
    """Explicit inspection state machine (see docs/diagrams/inspection-state-machine.svg)."""

    CREATED = "CREATED"
    OBSERVING = "OBSERVING"
    ANALYZING = "ANALYZING"
    REASONING = "REASONING"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    REOBSERVING = "REOBSERVING"
    DIAGNOSING = "DIAGNOSING"
    ACTION_PROPOSED = "ACTION_PROPOSED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class IncidentStatus(str, Enum):
    OPEN = "open"
    AWAITING_APPROVAL = "awaiting_approval"
    REMEDIATION_APPROVED = "remediation_approved"
    REMEDIATION_REJECTED = "remediation_rejected"
    RESOLVED = "resolved"


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TimelineKind(str, Enum):
    OBSERVATION = "observation"
    MEASUREMENT = "measurement"
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    DECISION = "decision"
    REQUEST = "request"
    USER_MESSAGE = "user_message"
    INCIDENT = "incident"
    APPROVAL = "approval"
    ERROR = "error"


class IndicatorState(str, Enum):
    RED = "RED"
    GREEN = "GREEN"
    AMBER = "AMBER"
    BLUE = "BLUE"
    WHITE = "WHITE"
    OFF = "OFF"
    UNKNOWN = "UNKNOWN"


class GaugeState(str, Enum):
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


# --------------------------------------------------------------------------
# Vision output
# --------------------------------------------------------------------------


class RegionSpec(BaseModel):
    """A named area of interest within an equipment profile."""

    region_id: str
    kind: Literal["indicator", "gauge", "switch", "display", "panel"]
    label: str
    #: Normalised coordinates (0..1) relative to image width/height.
    x: float
    y: float
    w: float
    h: float
    #: How the region was located.
    source: Literal["configured", "detected"] = "configured"
    #: Gauge-only calibration.
    scale_min: float | None = None
    scale_max: float | None = None
    unit: str | None = None
    #: Degrees, clockwise from up (12 o'clock), where the scale starts/ends.
    start_angle_deg: float | None = None
    end_angle_deg: float | None = None
    warn_above: float | None = None

    def pixel_box(self, width: int, height: int) -> tuple[int, int, int, int]:
        x = max(0, int(round(self.x * width)))
        y = max(0, int(round(self.y * height)))
        w = max(1, int(round(self.w * width)))
        h = max(1, int(round(self.h * height)))
        return x, y, min(w, width - x), min(h, height - y)


class ImageQuality(BaseModel):
    """Quality scores for one image, or for one region of it.

    All scores are normalised to ``0..1`` where ``1`` is best. Definitions and
    thresholds: ``docs/evaluation/methodology.md``.
    """

    blur_score: float
    exposure_quality: float
    mean_luma: float
    resolution_sufficient: bool
    width: int
    height: int
    requires_new_view: bool = False
    reason: str | None = None
    region_id: str | None = None


class Measurement(BaseModel):
    """A single structured measurement, with its provenance and confidence."""

    component_id: str
    component_type: Literal["indicator", "analog_gauge", "switch", "display", "panel", "image"]
    state: str | None = None
    value: float | None = None
    unit: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    method: str
    provenance: Provenance = Provenance.MEASURED
    requires_reinspection: bool = False
    notes: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class RegionAnalysis(BaseModel):
    region_id: str
    kind: str
    label: str
    box: tuple[int, int, int, int]
    measurements: list[Measurement] = Field(default_factory=list)
    quality: ImageQuality | None = None


class AnalysisResult(BaseModel):
    """Everything the vision engine extracted from one image."""

    image_id: str
    opencv_version: str
    analyzed_at: datetime = Field(default_factory=utcnow)
    profile_id: str
    quality: ImageQuality
    regions: list[RegionAnalysis] = Field(default_factory=list)
    measurements: list[Measurement] = Field(default_factory=list)
    annotations_path: str | None = None
    preprocessing: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0

    def low_confidence(self, floor: float) -> list[Measurement]:
        return [m for m in self.measurements if m.confidence < floor or m.requires_reinspection]


class ChangeEvent(BaseModel):
    component_id: str
    description: str
    previous: str | None = None
    current: str | None = None
    severity: Severity = Severity.INFO
    provenance: Provenance = Provenance.MEASURED


class ChangeReport(BaseModel):
    previous_image_id: str
    current_image_id: str
    changes: list[ChangeEvent] = Field(default_factory=list)
    method: str = "structured_measurement_diff"


# --------------------------------------------------------------------------
# Agent
# --------------------------------------------------------------------------


class TimelineEntry(BaseModel):
    id: int | None = None
    inspection_id: str
    kind: TimelineKind
    title: str
    detail: str = ""
    state: InspectionState | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class ToolCallRecord(BaseModel):
    id: int | None = None
    inspection_id: str
    step: int
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    ok: bool
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0
    source: Literal["model", "policy"] = "model"
    created_at: datetime = Field(default_factory=utcnow)


class ReinspectionRequest(BaseModel):
    target_region: str
    instruction: str
    reason: str
    created_at: datetime = Field(default_factory=utcnow)


class Assessment(BaseModel):
    """The agent's evaluation of the evidence available to it."""

    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    needs_more_evidence: bool = False
    recommended_next_step: str | None = None
    user_message: str = ""


# --------------------------------------------------------------------------
# Domain records
# --------------------------------------------------------------------------


class Observation(BaseModel):
    id: str
    inspection_id: str
    image_id: str
    original_name: str | None = None
    role: str = "primary"
    sequence: int = 0
    analysis: AnalysisResult | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Incident(BaseModel):
    id: str
    inspection_id: str
    title: str
    summary: str
    severity: Severity
    status: IncidentStatus = IncidentStatus.OPEN
    evidence_image_ids: list[str] = Field(default_factory=list)
    measurements: list[Measurement] = Field(default_factory=list)
    proposed_action: str | None = None
    approval_required: bool = True
    resolution_note: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Inspection(BaseModel):
    id: str
    mode: InspectionMode
    profile_id: str
    state: InspectionState = InspectionState.CREATED
    problem_statement: str = ""
    appliance: str | None = None
    demo_mode: bool = False
    observations: list[Observation] = Field(default_factory=list)
    observation_count: int = 0
    incident_id: str | None = None
    assessment: Assessment | None = None
    pending_request: ReinspectionRequest | None = None
    outcome: str | None = None
    resolved: bool | None = None
    step_count: int = 0
    tool_call_count: int = 0
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------
# API payloads
# --------------------------------------------------------------------------


class InspectionCreate(BaseModel):
    mode: InspectionMode
    problem_statement: str = Field(default="", max_length=2000)
    appliance: str | None = Field(default=None, max_length=120)
    profile_id: str | None = None
    demo_mode: bool | None = None


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    run_agent: bool = True


class ApprovalDecision(BaseModel):
    """The human decision on a proposed remediation.

    The decision is the route: ``/approve`` or ``/reject``. ``approved`` is accepted
    so a client may state the same thing in the body, and it is used for one purpose
    only -- to check that the client and the route agree. A body that contradicts the
    path is refused with a 422, because silently resolving it either way would mean an
    endpoint that approves when its caller asked it to reject.
    """

    note: str = Field(default="", max_length=1000)
    approved: bool | None = None


class VoiceRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    voice_id: str | None = None


class SystemStatus(BaseModel):
    name: str = "SightOps"
    tagline: str = "An Agentic Visual Reliability Engineer"
    opencv_version: str
    python_version: str
    providers: dict[str, bool]
    nebius_model: str
    nebius_vision_model: str
    elevenlabs_voice_id: str
    demo_mode_default: bool
    aws_integration: str = "NOT IMPLEMENTED"
    profiles: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    opencv_version: str
