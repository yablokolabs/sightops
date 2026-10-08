import { Link, useParams } from "react-router-dom";

import { api } from "../lib/api";
import { percent, relativeTime } from "../lib/format";
import { useAsync } from "../hooks/useAsync";
import { ErrorNote, Panel, SeverityBadge, Spinner } from "../components/Common";

export function IncidentList() {
  const incidents = useAsync(() => api.listIncidents(100), []);

  return (
    <div className="mx-auto max-w-6xl p-4 sm:p-8">
      <h1 className="text-2xl font-bold text-navy">Incidents</h1>
      <p className="mt-1 text-sm text-slate">
        Raised from measured evidence. Any remediation listed here is simulated and required human
        approval before it was recorded.
      </p>

      <div className="mt-6">
        {incidents.loading ? <Spinner label="Loading incidents…" /> : null}
        {incidents.error ? <ErrorNote message={incidents.error} /> : null}

        {incidents.data && incidents.data.length === 0 ? (
          <Panel title="No incidents">
            <p className="text-sm text-slate">
              Nothing has been raised yet. Run the pump-station demonstration from the Industrial
              workspace to see the full incident and approval flow.
            </p>
          </Panel>
        ) : null}

        {incidents.data && incidents.data.length > 0 ? (
          <ul className="space-y-3">
            {incidents.data.map((incident) => (
              <li key={incident.id}>
                <Link
                  to={`/incidents/${incident.id}`}
                  className="block rounded-xl border border-mist bg-white p-4 shadow-panel transition hover:border-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <SeverityBadge severity={incident.severity} />
                    <span className="font-mono text-[11px] uppercase tracking-wide text-slate">
                      {incident.status.replace(/_/g, " ")}
                    </span>
                    <span className="ml-auto text-[11px] text-slate">
                      {relativeTime(incident.created_at)}
                    </span>
                  </div>
                  <p className="mt-2 font-semibold text-ink">{incident.title}</p>
                  <p className="mt-1 text-sm text-slate">{incident.summary}</p>
                </Link>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}

export function IncidentDetail() {
  const { incidentId } = useParams<{ incidentId: string }>();
  const incident = useAsync(() => api.getIncident(incidentId as string), [incidentId]);

  if (!incidentId) return <ErrorNote message="No incident was selected." />;

  return (
    <div className="mx-auto max-w-4xl p-4 sm:p-8">
      {incident.loading ? <Spinner label="Loading the incident…" /> : null}
      {incident.error ? <ErrorNote message={incident.error} /> : null}

      {incident.data ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={incident.data.severity} />
            <span className="font-mono text-xs uppercase tracking-wide text-slate">
              {incident.data.status.replace(/_/g, " ")}
            </span>
            <Link
              to={`/inspections/${incident.data.inspection_id}`}
              className="ml-auto text-sm font-semibold text-brand hover:underline"
            >
              Open the inspection →
            </Link>
          </div>

          <h1 className="mt-3 text-2xl font-bold text-navy">{incident.data.title}</h1>
          <p className="mt-2 text-sm leading-relaxed text-slate">{incident.data.summary}</p>

          {incident.data.proposed_action ? (
            <div className="mt-5 rounded-xl border-2 border-amber/50 bg-amber/10 p-4">
              <p className="text-xs font-bold uppercase tracking-wider text-amber-dark">
                Simulated action — requires approval
              </p>
              <p className="mt-1 text-sm text-navy">{incident.data.proposed_action}</p>
              <p className="mt-2 text-[11px] text-slate">
                SightOps does not control machinery. Approving records a decision against a mock
                panel with no connection to plant equipment.
              </p>
            </div>
          ) : null}

          {incident.data.resolution_note ? (
            <p className="mt-5 rounded-lg border border-mist bg-white px-4 py-3 text-sm text-slate">
              <strong className="text-ink">Decision:</strong> {incident.data.resolution_note}
            </p>
          ) : null}

          <div className="mt-6">
            <Panel title={`Evidence attached (${incident.data.measurements.length} measurements)`}>
              {incident.data.measurements.length === 0 ? (
                <p className="text-sm text-slate">No measurements were attached to this incident.</p>
              ) : (
                <ul className="divide-y divide-mist">
                  {incident.data.measurements.map((measurement) => (
                    <li
                      key={measurement.component_id}
                      className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm"
                    >
                      <span className="font-mono text-xs text-navy">
                        {measurement.component_id}
                      </span>
                      <span className="text-ink">
                        {measurement.value === null
                          ? (measurement.state ?? "unknown")
                          : `${measurement.value} ${measurement.unit ?? ""}`}
                      </span>
                      <span className="font-mono text-xs text-slate">
                        {percent(measurement.confidence)}
                      </span>
                      <span className="text-[11px] uppercase tracking-wide text-slate">
                        {measurement.provenance}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>

          <p className="mt-4 font-mono text-[11px] text-slate">
            Incident {incident.data.id.slice(0, 8)} · created {relativeTime(incident.data.created_at)}{" "}
            · updated {relativeTime(incident.data.updated_at)}
          </p>
        </>
      ) : null}
    </div>
  );
}
