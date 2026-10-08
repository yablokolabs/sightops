import { useState } from "react";

import { percent } from "../lib/format";
import type { Assessment as AssessmentModel, Incident, Inspection } from "../lib/types";
import type { VoiceController } from "../hooks/useVoice";
import { ConfidenceBar, ErrorNote, Notice, Panel, SeverityBadge, Spinner } from "./Common";
import { VoiceControl } from "./VoiceButton";

/** The request for a better photograph, shown as a clear call to action. */
export function ReinspectionCard({ inspection }: { inspection: Inspection }) {
  const request = inspection.pending_request;
  if (!request) return null;
  return (
    <Notice tone="warn" title="SightOps needs a better view">
      <p>{request.instruction}</p>
      <p className="mt-1 text-xs opacity-90">
        <strong>Why:</strong> {request.reason}
      </p>
      <p className="mt-1 text-xs opacity-90">
        Target region: <span className="font-mono">{request.target_region}</span> — upload the new
        photograph above and the investigation continues from it.
      </p>
    </Notice>
  );
}

export function AssessmentPanel({
  assessment,
  voice,
  outcome
}: {
  assessment: AssessmentModel | null;
  voice: VoiceController;
  outcome?: string | null;
}) {
  if (!assessment) return null;
  return (
    <Panel title="Assessment">
      <p className="text-sm leading-relaxed text-ink">{assessment.summary}</p>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <span className="text-xs uppercase tracking-wide text-slate">Confidence</span>
        <ConfidenceBar value={assessment.confidence} />
        <span className="text-[11px] text-slate">
          {assessment.needs_more_evidence ? "More evidence required" : "Evidence sufficient"}
        </span>
      </div>

      {assessment.recommended_next_step ? (
        <p className="mt-3 rounded-lg border border-brand/25 bg-brand-pale px-3 py-2 text-sm text-navy">
          <strong>Next step:</strong> {assessment.recommended_next_step}
        </p>
      ) : null}

      {assessment.user_message ? (
        <p className="mt-3 text-sm italic text-slate">“{assessment.user_message}”</p>
      ) : null}

      <VoiceControl voice={voice} text={assessment.user_message || assessment.summary} />

      {outcome ? (
        <p className="mt-3 border-t border-mist pt-3 text-sm text-slate">{outcome}</p>
      ) : null}
    </Panel>
  );
}

export function ApprovalPanel({
  incident,
  pending,
  error,
  onDecide
}: {
  incident: Incident | null;
  pending: boolean;
  error: string | null;
  onDecide: (approved: boolean, note: string) => Promise<Incident | null>;
}) {
  const [note, setNote] = useState("");
  if (!incident) return null;

  const decided = incident.status.startsWith("remediation_");

  return (
    <Panel title="Incident and approval">
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={incident.severity} />
        <span className="font-mono text-[11px] uppercase tracking-wide text-slate">
          {incident.status.replace(/_/g, " ")}
        </span>
      </div>
      <h3 className="mt-2 text-sm font-semibold text-ink">{incident.title}</h3>
      <p className="mt-1 text-sm text-slate">{incident.summary}</p>

      {incident.proposed_action ? (
        <div className="mt-3 rounded-lg border-2 border-amber/50 bg-amber/10 p-3">
          <p className="text-[11px] font-bold uppercase tracking-wider text-amber-dark">
            Simulated action — requires approval
          </p>
          <p className="mt-1 text-sm text-navy">{incident.proposed_action}</p>
          <p className="mt-2 text-[11px] text-slate">
            This demonstrator is a mock panel with no connection to plant equipment. Approving
            records the decision; it does not operate machinery.
          </p>
        </div>
      ) : null}

      {incident.measurements.length > 0 ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs font-semibold text-brand">
            Evidence attached to this incident ({incident.measurements.length} measurements)
          </summary>
          <ul className="mt-2 space-y-1 text-xs text-slate">
            {incident.measurements.map((measurement) => (
              <li key={measurement.component_id} className="flex justify-between gap-3">
                <span className="font-mono">{measurement.component_id}</span>
                <span>
                  {measurement.value === null
                    ? (measurement.state ?? "unknown")
                    : `${measurement.value} ${measurement.unit ?? ""}`}{" "}
                  · {percent(measurement.confidence)}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {decided ? (
        <p className="mt-3 text-sm text-slate">
          <strong>Decision recorded:</strong> {incident.resolution_note}
        </p>
      ) : (
        <div className="mt-3">
          <label htmlFor="approval-note" className="block text-xs font-semibold text-ink">
            Note for the audit trail (optional)
          </label>
          <textarea
            id="approval-note"
            rows={2}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            className="mt-1 w-full rounded-lg border border-mist px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30"
            placeholder="For example: reviewed the annotated evidence and the gauge reading."
          />
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={pending}
              onClick={() => void onDecide(true, note)}
              className="inline-flex min-h-[44px] items-center rounded-lg bg-good px-5 text-sm font-semibold text-white hover:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-good disabled:opacity-50"
            >
              Approve simulated action
            </button>
            <button
              type="button"
              disabled={pending}
              onClick={() => void onDecide(false, note)}
              className="inline-flex min-h-[44px] items-center rounded-lg border border-bad/40 bg-white px-5 text-sm font-semibold text-bad hover:bg-bad/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-bad disabled:opacity-50"
            >
              Reject
            </button>
          </div>
          {pending ? <Spinner label="Recording the decision…" /> : null}
          {error ? (
            <div className="mt-2">
              <ErrorNote message={error} />
            </div>
          ) : null}
        </div>
      )}
    </Panel>
  );
}

export function OutcomePanel({
  inspection,
  pending,
  error,
  onResolve
}: {
  inspection: Inspection;
  pending: boolean;
  error: string | null;
  onResolve: (resolved: boolean) => Promise<boolean>;
}) {
  if (inspection.mode !== "home") return null;
  if (inspection.resolved !== null) {
    return (
      <Panel title="Did it work?">
        <p className="text-sm text-slate">
          {inspection.resolved
            ? "You told SightOps the problem is resolved. Thank you — that closes the inspection."
            : "You told SightOps the problem is not resolved. Reopen the workspace and upload another photograph, or ask for a technician."}
        </p>
      </Panel>
    );
  }
  return (
    <Panel title="Did that help?">
      <p className="text-base text-slate">
        Try the steps above, then tell SightOps what happened. This is what makes the next
        suggestion useful.
      </p>
      <div className="mt-3 flex flex-wrap gap-3">
        <button
          type="button"
          disabled={pending}
          onClick={() => void onResolve(true)}
          className="inline-flex min-h-[48px] items-center rounded-lg bg-good px-6 text-base font-semibold text-white hover:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-good disabled:opacity-50"
        >
          That worked
        </button>
        <button
          type="button"
          disabled={pending}
          onClick={() => void onResolve(false)}
          className="inline-flex min-h-[48px] items-center rounded-lg border border-bad/40 bg-white px-6 text-base font-semibold text-bad hover:bg-bad/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-bad disabled:opacity-50"
        >
          Still not working
        </button>
      </div>
      {error ? (
        <div className="mt-2">
          <ErrorNote message={error} />
        </div>
      ) : null}
    </Panel>
  );
}
