import { useState } from "react";

import { measurementValue, percent } from "../lib/format";
import type { AnalysisResult, Measurement } from "../lib/types";
import { ConfidenceBar, ProvenanceBadge } from "./Common";

function provenanceRank(measurement: Measurement): number {
  if (measurement.provenance === "measured") return 0;
  if (measurement.provenance === "inferred") return 1;
  return 2;
}

export function MeasurementTable({ analysis }: { analysis: AnalysisResult }) {
  const [open, setOpen] = useState<string | null>(null);
  const rows = [...analysis.measurements].sort(
    (a, b) => provenanceRank(a) - provenanceRank(b) || a.component_id.localeCompare(b.component_id)
  );

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">
          Measurements produced by OpenCV for this observation, with confidence and origin
        </caption>
        <thead>
          <tr className="border-b border-mist text-left text-[11px] uppercase tracking-wider text-slate">
            <th scope="col" className="py-2 pr-3 font-semibold">
              Component
            </th>
            <th scope="col" className="py-2 pr-3 font-semibold">
              Reading
            </th>
            <th scope="col" className="py-2 pr-3 font-semibold">
              Confidence
            </th>
            <th scope="col" className="py-2 font-semibold">
              Origin
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((measurement) => {
            const isOpen = open === measurement.component_id;
            return (
              <tr key={measurement.component_id} className="border-b border-mist/70 align-top">
                <td className="py-2 pr-3">
                  <span className="font-mono text-xs text-navy">{measurement.component_id}</span>
                  <span className="block text-[11px] text-slate">{measurement.component_type}</span>
                </td>
                <td className="py-2 pr-3">
                  <span
                    className={
                      measurement.value === null && measurement.component_type === "analog_gauge"
                        ? "font-medium text-amber-dark"
                        : "font-semibold text-ink"
                    }
                  >
                    {measurementValue(measurement)}
                  </span>
                  {measurement.requires_reinspection ? (
                    <span className="ml-2 inline-flex items-center rounded border border-amber/40 bg-amber/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-dark">
                      needs a better view
                    </span>
                  ) : null}
                </td>
                <td className="py-2 pr-3">
                  <ConfidenceBar value={measurement.confidence} />
                  <span className="sr-only">{percent(measurement.confidence)} confidence</span>
                </td>
                <td className="py-2">
                  <ProvenanceBadge provenance={measurement.provenance} />
                  <button
                    type="button"
                    onClick={() => setOpen(isOpen ? null : measurement.component_id)}
                    className="mt-1 block text-[11px] font-medium text-brand underline"
                    aria-expanded={isOpen}
                  >
                    {isOpen ? "Hide method" : "How was this measured?"}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {open ? <MeasurementDetail measurement={rows.find((row) => row.component_id === open)} /> : null}
    </div>
  );
}

function MeasurementDetail({ measurement }: { measurement: Measurement | undefined }) {
  if (!measurement) return null;
  const details = measurement.details as Record<string, unknown>;
  const criteria = (details["criteria"] ?? null) as Record<string, number> | null;

  return (
    <div className="mt-3 rounded-lg border border-mist bg-mist/20 p-3 text-xs">
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
        <div className="flex justify-between gap-2">
          <dt className="text-slate">Method</dt>
          <dd className="font-mono text-navy">{measurement.method}</dd>
        </div>
        {typeof details["dial_source"] === "string" ? (
          <div className="flex justify-between gap-2">
            <dt className="text-slate">Dial source</dt>
            <dd className="font-mono text-navy">{String(details["dial_source"])}</dd>
          </div>
        ) : null}
        {typeof details["needle_angle_deg"] === "number" ? (
          <div className="flex justify-between gap-2">
            <dt className="text-slate">Needle angle</dt>
            <dd className="font-mono text-navy">{details["needle_angle_deg"]}°</dd>
          </div>
        ) : null}
        {typeof details["ray_coverage"] === "number" ? (
          <div className="flex justify-between gap-2">
            <dt className="text-slate">Ray coverage</dt>
            <dd className="font-mono text-navy">{percent(details["ray_coverage"] as number)}</dd>
          </div>
        ) : null}
        {typeof details["peak_width_deg"] === "number" ? (
          <div className="flex justify-between gap-2">
            <dt className="text-slate">Peak width</dt>
            <dd className="font-mono text-navy">{details["peak_width_deg"]}°</dd>
          </div>
        ) : null}
      </dl>

      {criteria ? (
        <>
          <p className="mt-3 font-semibold text-slate">
            Confidence criteria (weighted to produce the score above)
          </p>
          <ul className="mt-1 grid grid-cols-2 gap-x-6 gap-y-0.5 sm:grid-cols-3">
            {Object.entries(criteria).map(([name, score]) => (
              <li key={name} className="flex justify-between gap-2">
                <span className="font-mono text-slate">{name}</span>
                <span className="font-mono text-navy">{percent(score)}</span>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {measurement.notes.length > 0 ? (
        <div className="mt-3">
          <p className="font-semibold text-amber-dark">Why this needs attention</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-slate">
            {measurement.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className="mt-3 text-[11px] text-slate">
        Provenance is recorded by the vision engine. A value tagged <strong>measured</strong> came
        from OpenCV on this image; anything tagged <strong>inferred</strong> is interpretation, not
        a measurement.
      </p>
    </div>
  );
}
