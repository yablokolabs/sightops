import { Component, type ErrorInfo, type ReactNode, useState } from "react";

import type { InspectionState, Provenance, Severity } from "../lib/types";
import { provenanceClasses, provenanceLabel, severityClasses, stateClasses } from "../lib/format";

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-slate" role="status">
      <span
        aria-hidden="true"
        className="h-4 w-4 animate-spin rounded-full border-2 border-brand/30 border-t-brand"
      />
      {label ? <span>{label}</span> : null}
    </span>
  );
}

export function ErrorNote({ message, onDismiss }: { message: string; onDismiss?: () => void }) {
  return (
    <div
      role="alert"
      className="flex items-start justify-between gap-3 rounded-lg border border-bad/30 bg-bad/5 px-3 py-2 text-sm text-bad"
    >
      <span>{message}</span>
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          className="rounded px-1 text-bad/70 hover:text-bad focus-visible:ring-2 focus-visible:ring-bad"
          aria-label="Dismiss error"
        >
          ✕
        </button>
      ) : null}
    </div>
  );
}

export function Notice({
  tone = "info",
  title,
  children
}: {
  tone?: "info" | "warn" | "good";
  title?: string;
  children: ReactNode;
}) {
  const tones = {
    info: "border-brand/25 bg-brand-pale text-navy",
    warn: "border-amber/40 bg-amber/10 text-amber-dark",
    good: "border-good/30 bg-good/5 text-good"
  } as const;
  return (
    <div className={`rounded-lg border px-3 py-2 text-sm ${tones[tone]}`}>
      {title ? <p className="mb-1 font-semibold">{title}</p> : null}
      {children}
    </div>
  );
}

export function Panel({
  title,
  actions,
  children,
  className = ""
}: {
  title?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-mist bg-white shadow-panel ${className}`}>
      {title ? (
        <header className="flex items-center justify-between gap-2 border-b border-mist px-4 py-3">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-slate">{title}</h2>
          {actions}
        </header>
      ) : null}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function StateChip({ state }: { state: InspectionState }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 font-mono text-[11px] font-semibold tracking-wide ${stateClasses(
        state
      )}`}
    >
      {state}
    </span>
  );
}

export function DemoChip() {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-amber/40 bg-amber/10 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-amber-dark">
      <span aria-hidden="true">●</span> Demo mode
    </span>
  );
}

export function ProvenanceBadge({ provenance }: { provenance: Provenance }) {
  return (
    <span
      title={provenanceLabel(provenance)}
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${provenanceClasses(
        provenance
      )}`}
    >
      {provenance}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span
      className={`inline-flex items-center rounded border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${severityClasses(
        severity
      )}`}
    >
      {severity}
    </span>
  );
}

export function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const tone = value >= 0.85 ? "bg-good" : value >= 0.6 ? "bg-brand" : "bg-amber";
  return (
    <span className="inline-flex items-center gap-2">
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-mist" aria-hidden="true">
        <span className={`block h-full ${tone}`} style={{ width: `${pct}%` }} />
      </span>
      <span className="font-mono text-xs text-slate">{pct}%</span>
    </span>
  );
}

/** Logo with a wordmark fallback if the asset has not been copied into public/. */
export function Logo({ size = 36 }: { size?: number }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <span
        className="grid place-items-center rounded-lg bg-navy font-bold text-white"
        style={{ width: size, height: size, fontSize: size * 0.42 }}
        aria-hidden="true"
      >
        SO
      </span>
    );
  }
  return (
    <img
      src="/SightOps.png"
      alt="SightOps"
      width={size}
      height={size}
      onError={() => setFailed(true)}
      className="rounded-lg"
    />
  );
}

interface BoundaryState {
  error: Error | null;
}

/** Keeps one broken view from blanking the whole application. */
export class ErrorBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  state: BoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Kept as console output: there is no client-side error service, and a
    // silent boundary would hide real regressions during development.
    console.error("SightOps view error", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="mx-auto max-w-2xl p-8">
          <ErrorNote message={`This view failed to render: ${this.state.error.message}`} />
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            className="mt-4 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-navy"
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
