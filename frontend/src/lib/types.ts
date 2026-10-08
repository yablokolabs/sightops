/**
 * Typed mirror of the backend's Pydantic models (`backend/app/models/schemas.py`).
 *
 * Field names are kept in snake_case exactly as the API returns them. Mapping to
 * camelCase here would add a translation layer that can drift silently; keeping
 * the wire names means a backend rename shows up as a TypeScript error instead.
 */

export type Provenance = "measured" | "inferred" | "user_reported" | "unknown";

export type InspectionMode = "home" | "industrial";

export type InspectionState =
  | "CREATED"
  | "OBSERVING"
  | "ANALYZING"
  | "REASONING"
  | "NEEDS_MORE_EVIDENCE"
  | "WAITING_FOR_USER"
  | "REOBSERVING"
  | "DIAGNOSING"
  | "ACTION_PROPOSED"
  | "AWAITING_APPROVAL"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export type Severity = "info" | "low" | "medium" | "high" | "critical";

export type TimelineKind =
  | "observation"
  | "measurement"
  | "reasoning"
  | "tool_call"
  | "tool_result"
  | "decision"
  | "request"
  | "user_message"
  | "incident"
  | "approval"
  | "error";

export type ComponentType =
  | "indicator"
  | "analog_gauge"
  | "switch"
  | "display"
  | "panel"
  | "image";

export interface Measurement {
  component_id: string;
  component_type: ComponentType;
  state: string | null;
  value: number | null;
  unit: string | null;
  confidence: number;
  method: string;
  provenance: Provenance;
  requires_reinspection: boolean;
  notes: string[];
  details: Record<string, unknown>;
}

export interface ImageQuality {
  blur_score: number;
  exposure_quality: number;
  mean_luma: number;
  resolution_sufficient: boolean;
  width: number;
  height: number;
  requires_new_view: boolean;
  reason: string | null;
  region_id: string | null;
}

export interface RegionAnalysis {
  region_id: string;
  kind: string;
  label: string;
  box: [number, number, number, number];
  measurements: Measurement[];
  quality: ImageQuality | null;
}

export interface AnalysisResult {
  image_id: string;
  opencv_version: string;
  analyzed_at: string;
  profile_id: string;
  quality: ImageQuality;
  regions: RegionAnalysis[];
  measurements: Measurement[];
  annotations_path: string | null;
  preprocessing: string[];
  latency_ms: number;
}

export interface Observation {
  id: string;
  inspection_id: string;
  image_id: string;
  original_name: string | null;
  role: string;
  sequence: number;
  analysis: AnalysisResult | null;
  created_at: string;
}

export interface ReinspectionRequest {
  target_region: string;
  instruction: string;
  reason: string;
  created_at: string;
}

export interface Assessment {
  summary: string;
  confidence: number;
  needs_more_evidence: boolean;
  recommended_next_step: string | null;
  user_message: string;
}

export interface Inspection {
  id: string;
  mode: InspectionMode;
  profile_id: string;
  state: InspectionState;
  problem_statement: string;
  appliance: string | null;
  demo_mode: boolean;
  observations: Observation[];
  observation_count: number;
  incident_id: string | null;
  assessment: Assessment | null;
  pending_request: ReinspectionRequest | null;
  outcome: string | null;
  resolved: boolean | null;
  step_count: number;
  tool_call_count: number;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface TimelineEntry {
  id: number | null;
  inspection_id: string;
  kind: TimelineKind;
  title: string;
  detail: string;
  state: InspectionState | null;
  data: Record<string, unknown>;
  created_at: string;
}

export interface ToolCallRecord {
  id: number | null;
  inspection_id: string;
  step: number;
  tool: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  result: Record<string, unknown>;
  error: string | null;
  duration_ms: number;
  source: "model" | "policy";
  created_at: string;
}

export interface Incident {
  id: string;
  inspection_id: string;
  title: string;
  summary: string;
  severity: Severity;
  status: string;
  evidence_image_ids: string[];
  measurements: Measurement[];
  proposed_action: string | null;
  approval_required: boolean;
  resolution_note: string | null;
  created_at: string;
  updated_at: string;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  database: boolean;
  opencv_version: string;
}

export interface SystemStatus {
  name: string;
  tagline: string;
  opencv_version: string;
  python_version: string;
  providers: Record<string, boolean>;
  nebius_model: string;
  nebius_vision_model: string;
  elevenlabs_voice_id: string;
  demo_mode_default: boolean;
  aws_integration: string;
  profiles: string[];
}

export interface OpencvStatus {
  opencv_version: string;
  opencv_major: number;
  is_opencv_5: boolean;
  claim: string;
}

export interface VoiceStatus {
  provider: string;
  configured: boolean;
  voice_id: string;
  model_id: string;
  message: string;
}

export interface DemoFlow {
  id: string;
  mode: InspectionMode;
  profile_id: string;
  steps: number;
  problem: string;
}

export interface DemoFlowsResponse {
  flows: DemoFlow[];
  note: string;
}

export interface InspectionCreate {
  mode: InspectionMode;
  problem_statement: string;
  appliance?: string | null;
  profile_id?: string | null;
  demo_mode?: boolean | null;
}

/** The only values the UI may render for a measurement's origin. */
export const PROVENANCE_LABELS: Record<Provenance, string> = {
  measured: "Measured by OpenCV",
  inferred: "Model inference",
  user_reported: "Reported by user",
  unknown: "Unknown"
};
