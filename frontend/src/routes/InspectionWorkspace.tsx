import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../lib/api";
import type { Incident } from "../lib/types";
import { latestAnalysed, useInspection } from "../hooks/useInspection";
import { useVoice } from "../hooks/useVoice";
import { ErrorNote, Notice, Spinner } from "../components/Common";
import { Workspace } from "../components/Workspace";

/**
 * One inspection, rendered in the three-column workspace.
 *
 * The incident is loaded separately from the inspection so that a failure to
 * load it cannot stop the measurements and the timeline from being shown.
 */
export function InspectionWorkspace() {
  const { inspectionId } = useParams<{ inspectionId: string }>();
  const controller = useInspection(inspectionId);
  const voice = useVoice();

  const [incident, setIncident] = useState<Incident | null>(null);
  const [incidentError, setIncidentError] = useState<string | null>(null);
  const [incidentPending, setIncidentPending] = useState(false);

  const incidentId = controller.bundle?.inspection.incident_id ?? null;

  useEffect(() => {
    let cancelled = false;
    if (!incidentId) {
      setIncident(null);
      return;
    }
    api
      .getIncident(incidentId)
      .then((value) => {
        if (!cancelled) {
          setIncident(value);
          setIncidentError(null);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setIncidentError(
            error instanceof Error ? error.message : "The incident could not be loaded."
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [incidentId, controller.bundle?.inspection.updated_at]);

  const onDecide = useCallback(
    async (approved: boolean, note: string): Promise<Incident | null> => {
      setIncidentPending(true);
      const result = await controller.decide(approved, note);
      setIncidentPending(false);
      if (result) setIncident(result);
      return result;
    },
    [controller]
  );

  const onNextScripted = useCallback(async () => {
    await controller.nextDemoObservation();
  }, [controller]);

  if (!inspectionId) {
    return (
      <div className="p-8">
        <ErrorNote message="No inspection was selected." />
      </div>
    );
  }

  const inspection = controller.bundle?.inspection ?? null;
  const analysed = latestAnalysed(controller.bundle);

  return (
    <Workspace
      controller={controller}
      voice={voice}
      incident={incident}
      incidentPending={incidentPending}
      incidentError={incidentError}
      onDecide={onDecide}
      extraActions={
        <>
          {inspection?.demo_mode ? (
            <button
              type="button"
              disabled={controller.pending}
              onClick={() => void onNextScripted()}
              className="inline-flex min-h-[44px] w-full items-center justify-center rounded-lg border border-amber/50 bg-amber/10 px-4 text-sm font-semibold text-amber-dark hover:bg-amber/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber disabled:opacity-50"
            >
              Run next scripted observation
            </button>
          ) : null}
          <button
            type="button"
            disabled={controller.pending}
            onClick={() => void controller.analyze()}
            className="inline-flex min-h-[44px] w-full items-center justify-center rounded-lg border border-mist bg-white px-4 text-sm font-semibold text-navy hover:bg-mist/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50"
          >
            Re-run the investigation on the latest image
          </button>
          {controller.pending ? <Spinner label="Working…" /> : null}
          {!analysed && inspection && inspection.observation_count > 0 ? (
            <Notice tone="info">
              The newest image has not been analysed yet. “Re-run the investigation” measures it.
            </Notice>
          ) : null}
          <p className="text-[11px] text-slate">
            <Link to="/inspections" className="font-medium text-brand underline">
              Back to inspection history
            </Link>
          </p>
        </>
      }
    />
  );
}
