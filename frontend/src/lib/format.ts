/** Display formatting shared by the workspace components. */

import type { InspectionState, Measurement, Provenance, Severity } from "./types";
import { PROVENANCE_LABELS } from "./types";

/** A measurement's headline value, or an explicit statement that there is none. */
export function measurementValue(measurement: Measurement): string {
  if (measurement.component_type === "analog_gauge") {
    if (measurement.value === null) return "Could not be read";
    return `${trimNumber(measurement.value)} ${measurement.unit ?? ""}`.trim();
  }
  if (measurement.value !== null) {
    return `${trimNumber(measurement.value)} ${measurement.unit ?? ""}`.trim();
  }
  return measurement.state ?? "Unknown";
}

export function trimNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/\.?0+$/, "");
}

export function percent(fraction: number): string {
  return `${Math.round(fraction * 100)}%`;
}

export function provenanceLabel(provenance: Provenance): string {
  return PROVENANCE_LABELS[provenance] ?? provenance;
}

/** Tailwind classes for the provenance badge. Measured facts are the strongest. */
export function provenanceClasses(provenance: Provenance): string {
  switch (provenance) {
    case "measured":
      return "bg-good/10 text-good border-good/30";
    case "inferred":
      return "bg-brand-pale text-brand border-brand/30";
    case "user_reported":
      return "bg-amber/10 text-amber-dark border-amber/30";
    default:
      return "bg-mist text-slate border-slate/30";
  }
}

export function stateClasses(state: InspectionState): string {
  switch (state) {
    case "COMPLETED":
      return "bg-good/10 text-good border-good/30";
    case "FAILED":
    case "CANCELLED":
      return "bg-bad/10 text-bad border-bad/30";
    case "AWAITING_APPROVAL":
    case "ACTION_PROPOSED":
      return "bg-amber/15 text-amber-dark border-amber/40";
    case "WAITING_FOR_USER":
    case "NEEDS_MORE_EVIDENCE":
      return "bg-brand-pale text-brand border-brand/30";
    default:
      return "bg-navy/5 text-navy border-navy/20";
  }
}

export function severityClasses(severity: Severity): string {
  switch (severity) {
    case "critical":
      return "bg-bad text-white border-bad";
    case "high":
      return "bg-bad/15 text-bad border-bad/40";
    case "medium":
      return "bg-amber/15 text-amber-dark border-amber/40";
    case "low":
      return "bg-brand-pale text-brand border-brand/30";
    default:
      return "bg-mist text-slate border-slate/30";
  }
}

/** Human sentence for each pipeline state, used in the workspace status chip. */
export const STATE_DESCRIPTIONS: Record<InspectionState, string> = {
  CREATED: "Created — waiting for an image",
  OBSERVING: "Observing",
  ANALYZING: "Measuring with OpenCV",
  REASONING: "Reasoning over the evidence",
  NEEDS_MORE_EVIDENCE: "Evidence is insufficient",
  WAITING_FOR_USER: "Waiting for you",
  REOBSERVING: "Re-observing",
  DIAGNOSING: "Forming a diagnosis",
  ACTION_PROPOSED: "Action proposed (simulated)",
  AWAITING_APPROVAL: "Awaiting your approval",
  COMPLETED: "Completed",
  FAILED: "Failed",
  CANCELLED: "Cancelled"
};

export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return new Date(iso).toLocaleString();
}

export function clockTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}

/**
 * The equivalent measurement from an earlier observation, if one exists.
 * Used by the workspace to show what changed between two views.
 */
export function findPrevious(
  measurements: Measurement[],
  componentId: string
): Measurement | undefined {
  return measurements.find((entry) => entry.component_id === componentId);
}
