import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { relativeTime, STATE_DESCRIPTIONS } from "../lib/format";
import type { Inspection } from "../lib/types";
import { useAsync } from "../hooks/useAsync";
import { DemoChip, ErrorNote, Panel, Spinner, StateChip } from "../components/Common";

export function InspectionHistory() {
  const inspections = useAsync(() => api.listInspections(100), []);

  return (
    <div className="mx-auto max-w-6xl p-4 sm:p-8">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-navy">Inspection history</h1>
          <p className="mt-1 text-sm text-slate">
            Every investigation is stored with its measurements, tool calls and decisions.
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            to="/home"
            className="inline-flex min-h-[40px] items-center rounded-lg bg-brand px-4 text-sm font-semibold text-white hover:bg-navy"
          >
            New appliance inspection
          </Link>
          <Link
            to="/industrial"
            className="inline-flex min-h-[40px] items-center rounded-lg border border-mist bg-white px-4 text-sm font-semibold text-navy hover:bg-mist/40"
          >
            New equipment inspection
          </Link>
        </div>
      </header>

      {inspections.loading ? <Spinner label="Loading inspections…" /> : null}
      {inspections.error ? <ErrorNote message={inspections.error} /> : null}

      {inspections.data && inspections.data.length === 0 ? (
        <Panel title="Nothing yet">
          <p className="text-sm text-slate">
            No inspection has been started. Try the dishwasher or pump-station demonstration from
            either workspace.
          </p>
        </Panel>
      ) : null}

      {inspections.data && inspections.data.length > 0 ? (
        <div className="overflow-x-auto rounded-xl border border-mist bg-white shadow-panel">
          <table className="w-full text-sm">
            <caption className="sr-only">Previous inspections</caption>
            <thead>
              <tr className="border-b border-mist text-left text-[11px] uppercase tracking-wider text-slate">
                <th scope="col" className="px-4 py-3 font-semibold">
                  Mode
                </th>
                <th scope="col" className="px-4 py-3 font-semibold">
                  State
                </th>
                <th scope="col" className="px-4 py-3 font-semibold">
                  Problem
                </th>
                <th scope="col" className="px-4 py-3 font-semibold">
                  Images
                </th>
                <th scope="col" className="px-4 py-3 font-semibold">
                  Started
                </th>
                <th scope="col" className="px-4 py-3 font-semibold" />
              </tr>
            </thead>
            <tbody>
              {inspections.data.map((inspection: Inspection) => (
                <tr key={inspection.id} className="border-b border-mist/70 last:border-0">
                  <td className="px-4 py-3">
                    <span className="font-medium text-ink">
                      {inspection.mode === "home" ? "Home" : "Industrial"}
                    </span>
                    {inspection.demo_mode ? (
                      <span className="mt-1 block">
                        <DemoChip />
                      </span>
                    ) : null}
                  </td>
                  <td className="px-4 py-3">
                    <StateChip state={inspection.state} />
                    <span className="mt-1 block text-[11px] text-slate">
                      {STATE_DESCRIPTIONS[inspection.state]}
                    </span>
                  </td>
                  <td className="max-w-sm px-4 py-3 text-slate">
                    <span className="line-clamp-2">{inspection.problem_statement || "—"}</span>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate">
                    {inspection.observation_count}
                  </td>
                  <td className="px-4 py-3 text-slate" title={inspection.created_at}>
                    {relativeTime(inspection.created_at)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Link
                      to={`/inspections/${inspection.id}`}
                      className="font-semibold text-brand hover:underline"
                    >
                      Open
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
