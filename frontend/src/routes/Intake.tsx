import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../lib/api";
import type { InspectionMode } from "../lib/types";
import { messageOf } from "../hooks/useAsync";
import { ErrorNote, Notice, Panel, Spinner } from "../components/Common";
import { UploadPanel } from "../components/Evidence";

interface IntakeCopy {
  heading: string;
  intro: string;
  placeholder: string;
  applianceLabel: string;
  demoFlow: string;
  demoLabel: string;
}

const COPY: Record<InspectionMode, IntakeCopy> = {
  home: {
    heading: "Troubleshoot an appliance",
    intro:
      "Take a photograph of the control panel or the part that is not working, then describe what happens. SightOps will measure what it can see, ask for a clearer picture if it needs one, and suggest what to try next.",
    placeholder:
      "For example: the dishwasher is switched on but nothing happens when I press start.",
    applianceLabel: "Which appliance? (optional)",
    demoFlow: "home",
    demoLabel: "Start the dishwasher demonstration"
  },
  industrial: {
    heading: "Inspect equipment",
    intro:
      "Upload a photograph of the equipment panel. SightOps measures gauges, indicators and switches with OpenCV, reports its confidence, and asks for a better view when the evidence is not good enough to act on.",
    placeholder:
      "For example: pump station 1 is showing a pressure alarm on the panel.",
    applianceLabel: "Equipment or asset tag (optional)",
    demoFlow: "industrial",
    demoLabel: "Start the pump-station demonstration"
  }
};

export function Intake({ mode }: { mode: InspectionMode }) {
  const navigate = useNavigate();
  const copy = COPY[mode];

  const [problem, setProblem] = useState("");
  const [appliance, setAppliance] = useState("");
  const [demoMode, setDemoMode] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<File | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);

  const start = useCallback(
    async (file: File | null) => {
      setPending(true);
      setError(null);
      try {
        const inspection = await api.createInspection({
          mode,
          problem_statement: problem.trim() || copy.placeholder,
          appliance: appliance.trim() || null,
          demo_mode: demoMode
        });
        if (file) {
          await api.uploadImage(inspection.id, file, true);
        } else {
          await api.analyzeInspection(inspection.id).catch(() => undefined);
        }
        navigate(`/inspections/${inspection.id}`);
      } catch (caught) {
        setError(messageOf(caught));
      } finally {
        setPending(false);
      }
    },
    [appliance, copy.placeholder, demoMode, mode, navigate, problem]
  );

  const startDemo = useCallback(async () => {
    setPending(true);
    setError(null);
    try {
      const inspection = await api.startDemo(copy.demoFlow);
      navigate(`/inspections/${inspection.id}`);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setPending(false);
    }
  }, [copy.demoFlow, navigate]);

  return (
    <div className="mx-auto max-w-3xl p-4 sm:p-8">
      <h1 className="text-2xl font-bold text-navy">{copy.heading}</h1>
      <p className="mt-2 text-base leading-relaxed text-slate">{copy.intro}</p>

      <div className="mt-6 space-y-4">
        <Panel title="Step 1 — describe the problem">
          <label htmlFor="problem" className="block text-base font-semibold text-ink">
            What is happening?
          </label>
          <textarea
            id="problem"
            rows={4}
            value={problem}
            onChange={(event) => setProblem(event.target.value)}
            placeholder={copy.placeholder}
            className="mt-2 w-full rounded-lg border border-mist px-3 py-3 text-lg leading-relaxed focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30"
          />
          <label htmlFor="appliance" className="mt-4 block text-base font-semibold text-ink">
            {copy.applianceLabel}
          </label>
          <input
            id="appliance"
            value={appliance}
            onChange={(event) => setAppliance(event.target.value)}
            className="mt-2 w-full rounded-lg border border-mist px-3 py-3 text-lg focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30"
          />
        </Panel>

        <Panel title="Step 2 — add a photograph">
          <UploadPanel
            onUpload={(file) => {
              fileRef.current = file;
              setFileName(file.name);
            }}
            pending={false}
            error={null}
          />
          {fileName ? (
            <p className="mt-2 text-sm text-good">
              Attached: <span className="font-mono">{fileName}</span> — it will be measured when the
              inspection starts.
            </p>
          ) : (
            <p className="mt-2 text-sm text-slate">
              You can also start without a photograph and add one from the workspace.
            </p>
          )}
        </Panel>

        <Panel title="Step 3 — choose how SightOps reasons">
          <fieldset>
            <legend className="sr-only">Reasoning mode</legend>
            <div className="space-y-2">
              <label className="flex min-h-[44px] cursor-pointer items-start gap-3 rounded-lg border border-mist p-3 hover:bg-mist/30">
                <input
                  type="radio"
                  name="reasoning"
                  checked={!demoMode}
                  onChange={() => setDemoMode(false)}
                  className="mt-1 h-5 w-5 accent-brand"
                />
                <span>
                  <span className="block text-base font-semibold text-ink">Live AI mode</span>
                  <span className="block text-sm text-slate">
                    The Nebius model chooses what to measure next, using the OpenCV measurements as
                    its evidence.
                  </span>
                </span>
              </label>
              <label className="flex min-h-[44px] cursor-pointer items-start gap-3 rounded-lg border border-mist p-3 hover:bg-mist/30">
                <input
                  type="radio"
                  name="reasoning"
                  checked={demoMode}
                  onChange={() => setDemoMode(true)}
                  className="mt-1 h-5 w-5 accent-brand"
                />
                <span>
                  <span className="block text-base font-semibold text-ink">
                    Demo mode (deterministic)
                  </span>
                  <span className="block text-sm text-slate">
                    A fixed policy picks the next step from the same measurements, so a run is
                    reproducible and costs no API calls. Clearly labelled everywhere it appears.
                  </span>
                </span>
              </label>
            </div>
          </fieldset>
        </Panel>

        {error ? <ErrorNote message={error} onDismiss={() => setError(null)} /> : null}

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={pending}
            onClick={() => void start(fileRef.current)}
            className="inline-flex min-h-[52px] items-center rounded-xl bg-brand px-6 text-lg font-semibold text-white hover:bg-navy focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-light disabled:opacity-50"
          >
            {pending ? "Starting…" : "Start the inspection"}
          </button>
          <button
            type="button"
            disabled={pending}
            onClick={() => void startDemo()}
            className="inline-flex min-h-[52px] items-center rounded-xl border border-amber/50 bg-amber/10 px-6 text-base font-semibold text-amber-dark hover:bg-amber/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber disabled:opacity-50"
          >
            {copy.demoLabel}
          </button>
          {pending ? <Spinner label="Preparing the inspection…" /> : null}
        </div>

        <Notice tone="info" title="Safety">
          SightOps is decision support. It will not tell you to open energised equipment, and it
          never controls machinery. Any remedial action in the industrial demonstration is
          simulated and requires a human to approve it.
        </Notice>
      </div>
    </div>
  );
}
