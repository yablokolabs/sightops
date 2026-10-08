import { useEffect, useMemo, useState, type ReactNode } from "react";

import { STATE_DESCRIPTIONS } from "../lib/format";
import type { Incident } from "../lib/types";
import type { InspectionController } from "../hooks/useInspection";
import { latestAnalysed } from "../hooks/useInspection";
import type { VoiceController } from "../hooks/useVoice";
import { AssessmentPanel, ApprovalPanel, OutcomePanel, ReinspectionCard } from "./Assessment";
import { Composer } from "./Composer";
import { DemoChip, ErrorNote, Panel, Spinner, StateChip } from "./Common";
import { EvidenceViewer, UploadPanel } from "./Evidence";
import { MeasurementTable } from "./MeasurementTable";
import { Timeline } from "./Timeline";

export function Workspace({
  controller,
  voice,
  incident,
  incidentPending,
  incidentError,
  onDecide,
  extraActions
}: {
  controller: InspectionController;
  voice: VoiceController;
  incident: Incident | null;
  incidentPending: boolean;
  incidentError: string | null;
  onDecide: (approved: boolean, note: string) => Promise<Incident | null>;
  extraActions?: ReactNode;
}) {
  const bundle = controller.bundle;
  const [selectedImageId, setSelectedImageId] = useState<string | null>(null);

  const observations = bundle?.observations ?? [];
  const newestImageId = observations.length > 0 ? observations[observations.length - 1].image_id : null;

  // Follow the newest observation unless the viewer has deliberately picked an
  // older one, so a new upload is shown immediately.
  useEffect(() => {
    if (observations.length === 0) {
      setSelectedImageId(null);
      return;
    }
    setSelectedImageId((current) => {
      if (current && observations.some((observation) => observation.image_id === current)) {
        return current;
      }
      return newestImageId;
    });
  }, [observations, newestImageId]);

  const analysed = useMemo(() => latestAnalysed(bundle), [bundle]);

  if (controller.loading && !bundle) {
    return (
      <div className="p-8">
        <Spinner label="Loading the inspection…" />
      </div>
    );
  }

  if (controller.error || !bundle) {
    return (
      <div className="p-8">
        <ErrorNote message={controller.error ?? "This inspection could not be loaded."} />
      </div>
    );
  }

  const { inspection, timeline, toolCalls } = bundle;
  const latestAnalysis = analysed?.analysis ?? null;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-mist bg-white px-4 py-3">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-3">
          <h1 className="text-base font-bold text-ink">
            {inspection.mode === "home" ? "Appliance troubleshooting" : "Equipment inspection"}
          </h1>
          <StateChip state={inspection.state} />
          {inspection.demo_mode ? <DemoChip /> : null}
          <p className="text-sm text-slate">{STATE_DESCRIPTIONS[inspection.state]}</p>
          <p className="ml-auto font-mono text-[11px] text-slate">
            {inspection.id.slice(0, 8)} · {inspection.profile_id} · {inspection.tool_call_count} tool
            calls · step {inspection.step_count}
          </p>
        </div>
        {inspection.demo_mode ? (
          <p className="mx-auto mt-2 max-w-[1600px] rounded-lg border border-amber/40 bg-amber/10 px-3 py-2 text-xs text-amber-dark">
            <strong>Demo mode:</strong> the sequence of photographs is scripted, but every
            measurement below is produced by OpenCV from those images. This is not a replay of
            stored results and it is not live model reasoning.
          </p>
        ) : null}
        {inspection.problem_statement ? (
          <p className="mx-auto mt-2 max-w-[1600px] text-sm text-slate">
            <strong className="text-ink">Reported problem:</strong> {inspection.problem_statement}
          </p>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto bg-mist/20">
        <div className="mx-auto grid max-w-[1600px] grid-cols-1 gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)_minmax(0,1.15fr)]">
          <div className="space-y-4">
            <Panel title="Camera / image">
              <UploadPanel
                onUpload={(file) => controller.upload(file)}
                pending={controller.pending}
                error={controller.actionError}
              />
              {extraActions ? <div className="mt-3 space-y-2">{extraActions}</div> : null}
            </Panel>

            <ReinspectionCard inspection={inspection} />

            {latestAnalysis ? (
              <Panel title="Measurement detail">
                <MeasurementTable analysis={latestAnalysis} />
                <p className="mt-3 text-[11px] text-slate">
                  Measured in {latestAnalysis.latency_ms.toFixed(0)} ms with OpenCV{" "}
                  {latestAnalysis.opencv_version}.
                </p>
              </Panel>
            ) : null}
          </div>

          <div className="space-y-4">
            <Panel title="Visual evidence">
              <EvidenceViewer
                inspectionId={inspection.id}
                observations={observations}
                selectedId={selectedImageId}
                onSelect={setSelectedImageId}
              />
            </Panel>

            <AssessmentPanel
              assessment={inspection.assessment}
              voice={voice}
              outcome={inspection.outcome}
            />

            {incident ? (
              <ApprovalPanel
                incident={incident}
                pending={incidentPending}
                error={incidentError}
                onDecide={onDecide}
              />
            ) : null}

            <OutcomePanel
              inspection={inspection}
              pending={controller.pending}
              error={controller.actionError}
              onResolve={controller.resolve}
            />
          </div>

          <div className="flex min-h-[420px] flex-col rounded-xl border border-mist bg-mist/20 shadow-panel">
            <header className="flex items-center justify-between border-b border-mist bg-white px-4 py-3">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-slate">
                Agent timeline
              </h2>
              <span className="font-mono text-[10px] text-slate">
                {timeline.length} entries · {toolCalls.length} tool calls
              </span>
            </header>
            <div className="min-h-0 flex-1 p-3">
              <Timeline
                entries={timeline}
                loading={controller.loading}
                error={null}
                voice={voice}
              />
            </div>
            {controller.pending ? (
              <p className="border-t border-mist bg-white px-4 py-2">
                <Spinner label="Working…" />
              </p>
            ) : null}
          </div>
        </div>
      </div>

      <Composer
        onSend={controller.sendMessage}
        pending={controller.pending}
        error={controller.actionError}
        placeholder={
          inspection.mode === "home"
            ? "Tell SightOps what you see or what happened next…"
            : "Ask SightOps about the measurements…"
        }
      />
    </div>
  );
}
