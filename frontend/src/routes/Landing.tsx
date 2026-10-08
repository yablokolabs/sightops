import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { useAsync } from "../hooks/useAsync";
import { Logo, Notice, Panel, Spinner } from "../components/Common";

export function Landing() {
  const status = useAsync(() => api.systemStatus(), []);
  const health = useAsync(() => api.health(), []);

  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:py-16">
      <div className="flex flex-col items-center text-center">
        <Logo size={96} />
        <h1 className="mt-6 text-4xl font-extrabold tracking-tight text-navy sm:text-5xl">
          SightOps
        </h1>
        <p className="mt-2 text-lg font-medium text-brand">An Agentic Visual Reliability Engineer</p>
        <p className="mt-4 text-2xl font-bold tracking-[0.14em] text-amber-dark">
          SEE. DIAGNOSE. ACT.
        </p>
        <p className="mt-6 max-w-2xl text-base leading-relaxed text-slate">
          SightOps uses computer vision and agentic AI to investigate equipment problems, gather
          better visual evidence when uncertain, and guide users toward safe actions.
        </p>
      </div>

      <div className="mt-10 grid gap-4 sm:grid-cols-2">
        <Link
          to="/home"
          className="group rounded-2xl border border-mist bg-white p-6 shadow-panel transition hover:border-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
        >
          <h2 className="text-xl font-bold text-navy">Troubleshoot an Appliance</h2>
          <p className="mt-2 text-sm leading-relaxed text-slate">
            Point your phone at the appliance, describe what happens, and SightOps will measure what
            it can see and ask for a clearer picture when it needs one.
          </p>
          <p className="mt-4 text-sm font-semibold text-brand group-hover:underline">
            Start household troubleshooting →
          </p>
        </Link>

        <Link
          to="/industrial"
          className="group rounded-2xl border border-mist bg-white p-6 shadow-panel transition hover:border-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
        >
          <h2 className="text-xl font-bold text-navy">Inspect Equipment</h2>
          <p className="mt-2 text-sm leading-relaxed text-slate">
            Read analog gauges, indicator lamps and switch positions with measured confidence, follow
            the agent's investigation, and approve or reject a simulated remediation.
          </p>
          <p className="mt-4 text-sm font-semibold text-brand group-hover:underline">
            Start equipment inspection →
          </p>
        </Link>
      </div>

      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        <Panel title="How it works">
          <ol className="space-y-2 text-sm text-slate">
            <li>
              <strong className="text-ink">1. Observe.</strong> You supply a photograph.
            </li>
            <li>
              <strong className="text-ink">2. Measure.</strong> OpenCV extracts gauges, indicators,
              switches and image quality as structured numbers.
            </li>
            <li>
              <strong className="text-ink">3. Evaluate.</strong> Every measurement carries a
              confidence and the criteria behind it.
            </li>
            <li>
              <strong className="text-ink">4. Investigate.</strong> When the evidence is not good
              enough, the agent asks for a better view instead of guessing.
            </li>
            <li>
              <strong className="text-ink">5. Decide and act.</strong> It states a conclusion, and
              any consequential action needs your approval.
            </li>
          </ol>
        </Panel>

        <Panel title="System status">
          {status.loading || health.loading ? <Spinner label="Checking the backend…" /> : null}
          {status.error ? <Notice tone="warn">{status.error}</Notice> : null}
          {status.data ? (
            <dl className="space-y-2 text-sm">
              <div className="flex items-center justify-between gap-3">
                <dt className="text-slate">OpenCV version</dt>
                <dd className="font-mono font-semibold text-navy">{status.data.opencv_version}</dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt className="text-slate">Reasoning model</dt>
                <dd className="font-mono text-navy">{status.data.nebius_model}</dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt className="text-slate">Vision model</dt>
                <dd className="font-mono text-navy">{status.data.nebius_vision_model}</dd>
              </div>
              <div className="pt-2">
                <dt className="text-xs uppercase tracking-wide text-slate">Providers configured</dt>
                <dd className="mt-1 space-y-1">
                  {Object.entries(status.data.providers).map(([name, configured]) => (
                    <span key={name} className="flex items-center gap-2 text-sm">
                      <span
                        aria-hidden="true"
                        className={`h-2 w-2 rounded-full ${configured ? "bg-good" : "bg-bad"}`}
                      />
                      <span className="font-mono text-xs text-slate">{name}</span>
                      <span className="text-xs text-slate">
                        {configured ? "configured" : "not configured"}
                      </span>
                    </span>
                  ))}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3 pt-2">
                <dt className="text-slate">AWS integration</dt>
                <dd className="font-mono text-xs font-semibold text-amber-dark">
                  {status.data.aws_integration}
                </dd>
              </div>
            </dl>
          ) : null}
          <p className="mt-3 text-[11px] text-slate">
            Only the presence of a credential is ever reported — no key or secret is sent to the
            browser.
          </p>
        </Panel>
      </div>

      <p className="mt-8 text-center text-sm text-slate">
        Built for the OpenCV AI Competition 2026 by Yabloko Labs.
      </p>
    </div>
  );
}
