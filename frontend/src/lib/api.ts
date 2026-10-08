/**
 * Typed client for the SightOps API.
 *
 * Everything goes through {@link request}, so error handling, request-id
 * surfaced messages and JSON parsing live in one place. Calls are relative to
 * the current origin: Vite proxies `/api` and `/health` to the backend in
 * development, and a reverse proxy does the same in deployment.
 */

import type {
  Assessment,
  DemoFlowsResponse,
  HealthResponse,
  Incident,
  Inspection,
  InspectionCreate,
  Observation,
  OpencvStatus,
  SystemStatus,
  TimelineEntry,
  ToolCallRecord,
  VoiceStatus
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly requestId: string | null;

  constructor(status: number, message: string, requestId: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.requestId = requestId;
  }
}

/** Turn FastAPI's varied `detail` shapes into one readable sentence. */
function readDetail(payload: unknown): string {
  if (typeof payload === "string") return payload;
  if (payload && typeof payload === "object") {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((entry) => {
          if (entry && typeof entry === "object" && "msg" in entry) {
            const msg = (entry as { msg?: unknown }).msg;
            if (typeof msg === "string") return msg;
          }
          return JSON.stringify(entry);
        })
        .join("; ");
    }
  }
  return "The request failed.";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isForm = typeof FormData !== "undefined" && init?.body instanceof FormData;
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: {
        Accept: "application/json",
        // A multipart body must set its own boundary, so only JSON requests
        // declare a content type here.
        ...(isForm || init?.body === undefined ? {} : { "Content-Type": "application/json" })
      }
    });
  } catch {
    throw new ApiError(0, "The SightOps backend could not be reached.", null);
  }

  const requestId = response.headers.get("X-Request-ID");

  if (!response.ok) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    const message = readDetail(payload) || `Request failed with status ${response.status}.`;
    throw new ApiError(response.status, message, requestId);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function requestBlob(path: string, init?: RequestInit): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError(0, "The SightOps backend could not be reached.", null);
  }
  if (!response.ok) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    throw new ApiError(
      response.status,
      readDetail(payload) || `Request failed with status ${response.status}.`,
      response.headers.get("X-Request-ID")
    );
  }
  return response.blob();
}

export const api = {
  health: () => request<HealthResponse>("/health"),
  systemStatus: () => request<SystemStatus>("/api/system/status"),
  opencvStatus: () => request<OpencvStatus>("/api/system/opencv"),

  listInspections: (limit = 50) =>
    request<Inspection[]>(`/api/inspections?limit=${encodeURIComponent(String(limit))}`),
  getInspection: (id: string) => request<Inspection>(`/api/inspections/${encodeURIComponent(id)}`),
  createInspection: (payload: InspectionCreate) =>
    request<Inspection>("/api/inspections", { method: "POST", body: JSON.stringify(payload) }),
  analyzeInspection: (id: string) =>
    request<Inspection>(`/api/inspections/${encodeURIComponent(id)}/analyze`, { method: "POST" }),
  sendMessage: (id: string, content: string, runAgent = true) =>
    request<Inspection>(`/api/inspections/${encodeURIComponent(id)}/messages`, {
      method: "POST",
      body: JSON.stringify({ content, run_agent: runAgent })
    }),
  approve: (id: string, note: string) =>
    request<Incident>(`/api/inspections/${encodeURIComponent(id)}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved: true, note })
    }),
  reject: (id: string, note: string) =>
    request<Incident>(`/api/inspections/${encodeURIComponent(id)}/reject`, {
      method: "POST",
      body: JSON.stringify({ approved: false, note })
    }),
  resolve: (id: string, resolved: boolean) =>
    request<Inspection>(
      `/api/inspections/${encodeURIComponent(id)}/resolve?resolved=${resolved ? "true" : "false"}`,
      { method: "POST" }
    ),

  timeline: (id: string) =>
    request<TimelineEntry[]>(`/api/inspections/${encodeURIComponent(id)}/timeline`),
  observations: (id: string) =>
    request<Observation[]>(`/api/inspections/${encodeURIComponent(id)}/observations`),
  toolCalls: (id: string) =>
    request<ToolCallRecord[]>(`/api/inspections/${encodeURIComponent(id)}/tool-calls`),

  evidenceUrl: (inspectionId: string, imageId: string, annotated: boolean) =>
    `/api/inspections/${encodeURIComponent(inspectionId)}/evidence/${encodeURIComponent(imageId)}${
      annotated ? "?annotated=true" : ""
    }`,

  async uploadImage(id: string, file: File, runAgent = true): Promise<Inspection> {
    const form = new FormData();
    form.append("file", file);
    form.append("run_agent", runAgent ? "true" : "false");
    return request<Inspection>(`/api/inspections/${encodeURIComponent(id)}/images`, {
      method: "POST",
      body: form
    });
  },

  listIncidents: (limit = 100) => request<Incident[]>(`/api/incidents?limit=${limit}`),
  getIncident: (id: string) => request<Incident>(`/api/incidents/${encodeURIComponent(id)}`),

  voiceStatus: () => request<VoiceStatus>("/api/voice/status"),
  synthesize: (text: string, voiceId?: string) =>
    requestBlob("/api/voice/synthesize", {
      method: "POST",
      body: JSON.stringify({ text, voice_id: voiceId ?? null })
    }),

  demoFlows: () => request<DemoFlowsResponse>("/api/demo/flows"),
  startDemo: (flow: string) =>
    request<Inspection>(`/api/demo/${encodeURIComponent(flow)}`, { method: "POST" }),
  nextDemoObservation: (inspectionId: string) =>
    request<Inspection>(
      `/api/demo/${encodeURIComponent(inspectionId)}/next-observation`,
      { method: "POST" }
    )
};

export type { Assessment };
