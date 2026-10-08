import { api } from "../lib/api";
import { useAsync } from "../hooks/useAsync";
import { ErrorNote, Notice, Panel, Spinner } from "../components/Common";

export function SystemStatusPage() {
  const status = useAsync(() => api.systemStatus(), []);
  const opencv = useAsync(() => api.opencvStatus(), []);
  const health = useAsync(() => api.health(), []);
  const voice = useAsync(() => api.voiceStatus(), []);

  return (
    <div className="mx-auto max-w-4xl p-4 sm:p-8">
      <h1 className="text-2xl font-bold text-navy">System status</h1>
      <p className="mt-1 text-sm text-slate">
        Configuration and capability of the running SightOps instance. Credential values are never
        reported — only whether each provider is configured.
      </p>

      <div className="mt-6 space-y-4">
        <Panel title="Runtime">
          {health.loading || opencv.loading ? <Spinner label="Checking…" /> : null}
          {health.error ? <ErrorNote message={health.error} /> : null}
          {opencv.error ? <ErrorNote message={opencv.error} /> : null}
          {opencv.data ? (
            <>
              <div className="rounded-lg border border-good/40 bg-good/5 px-3 py-2">
                <p className="text-sm font-semibold text-good">{opencv.data.claim}</p>
                <p className="mt-1 font-mono text-xs text-slate">
                  cv2.__version__ = {opencv.data.opencv_version} (major {opencv.data.opencv_major})
                </p>
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
                <div>
                  <dt className="text-xs uppercase tracking-wide text-slate">Backend health</dt>
                  <dd className="font-mono text-navy">{health.data?.status ?? "unknown"}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-slate">Database</dt>
                  <dd className="font-mono text-navy">
                    {health.data?.database ? "connected" : "unavailable"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-slate">Python</dt>
                  <dd className="font-mono text-navy">{status.data?.python_version ?? "—"}</dd>
                </div>
              </dl>
            </>
          ) : null}
        </Panel>

        <Panel title="Providers">
          {status.loading ? <Spinner label="Loading provider status…" /> : null}
          {status.error ? <ErrorNote message={status.error} /> : null}
          {status.data ? (
            <>
              <ul className="space-y-2">
                {Object.entries(status.data.providers).map(([name, configured]) => (
                  <li key={name} className="flex items-center gap-3 text-sm">
                    <span
                      aria-hidden="true"
                      className={`h-2.5 w-2.5 rounded-full ${configured ? "bg-good" : "bg-bad"}`}
                    />
                    <span className="font-mono text-xs text-slate">{name}</span>
                    <span className={configured ? "text-good" : "text-bad"}>
                      {configured ? "configured" : "not configured"}
                    </span>
                  </li>
                ))}
              </ul>
              <dl className="mt-4 space-y-2 text-sm">
                <div className="flex flex-wrap justify-between gap-2">
                  <dt className="text-slate">Reasoning model</dt>
                  <dd className="font-mono text-navy">{status.data.nebius_model}</dd>
                </div>
                <div className="flex flex-wrap justify-between gap-2">
                  <dt className="text-slate">Multimodal model</dt>
                  <dd className="font-mono text-navy">{status.data.nebius_vision_model}</dd>
                </div>
                <div className="flex flex-wrap justify-between gap-2">
                  <dt className="text-slate">Voice</dt>
                  <dd className="font-mono text-navy">{status.data.elevenlabs_voice_id}</dd>
                </div>
                <div className="flex flex-wrap justify-between gap-2">
                  <dt className="text-slate">Equipment profiles</dt>
                  <dd className="font-mono text-navy">{status.data.profiles.join(", ")}</dd>
                </div>
                <div className="flex flex-wrap justify-between gap-2">
                  <dt className="text-slate">Deterministic demo mode</dt>
                  <dd className="font-mono text-navy">
                    {status.data.demo_mode_default ? "enabled by default" : "off by default"}
                  </dd>
                </div>
              </dl>
            </>
          ) : null}
        </Panel>

        <Panel title="Voice guidance">
          {voice.loading ? <Spinner label="Checking voice…" /> : null}
          {voice.error ? <ErrorNote message={voice.error} /> : null}
          {voice.data ? (
            <div className="space-y-2 text-sm">
              <p className={voice.data.configured ? "text-good" : "text-amber-dark"}>
                {voice.data.message}
              </p>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-1">
                <div>
                  <dt className="text-xs uppercase tracking-wide text-slate">Provider</dt>
                  <dd className="font-mono text-navy">{voice.data.provider}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-slate">Model</dt>
                  <dd className="font-mono text-navy">{voice.data.model_id}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-slate">Voice id</dt>
                  <dd className="font-mono text-navy">{voice.data.voice_id}</dd>
                </div>
              </dl>
            </div>
          ) : null}
        </Panel>

        <Panel title="AWS integration">
          <Notice tone="warn" title="Not implemented">
            SightOps runs entirely on a CPU-only Azure VM. No AWS resource has been created and no
            AWS credentials are required to run this build. Planned target services — Graviton with
            the Cloud-Optimized OpenCV Library, Amazon Bedrock, S3, DynamoDB, Lambda and CloudWatch —
            are documented as a design in <span className="font-mono">docs/architecture/aws.md</span>{" "}
            and are behind provider interfaces, but none of them has been deployed or benchmarked.
          </Notice>
        </Panel>
      </div>
    </div>
  );
}

export function NotFound() {
  return (
    <div className="mx-auto max-w-2xl p-8">
      <h1 className="text-2xl font-bold text-navy">Page not found</h1>
      <p className="mt-2 text-sm text-slate">
        That route does not exist. Use the navigation above to reach a workspace.
      </p>
    </div>
  );
}
