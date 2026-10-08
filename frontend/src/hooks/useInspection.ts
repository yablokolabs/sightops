import { useCallback, useMemo, useState } from "react";

import { api } from "../lib/api";
import type { Incident, Inspection, Observation, TimelineEntry, ToolCallRecord } from "../lib/types";
import { messageOf, useAsync } from "./useAsync";

export interface InspectionBundle {
  inspection: Inspection;
  timeline: TimelineEntry[];
  observations: Observation[];
  toolCalls: ToolCallRecord[];
}

export interface InspectionController {
  bundle: InspectionBundle | null;
  loading: boolean;
  error: string | null;
  /** Error from the most recent mutation, kept separate from load errors. */
  actionError: string | null;
  pending: boolean;
  reload: () => Promise<void>;
  upload: (file: File) => Promise<boolean>;
  sendMessage: (content: string) => Promise<boolean>;
  analyze: () => Promise<boolean>;
  decide: (approved: boolean, note: string) => Promise<Incident | null>;
  resolve: (resolved: boolean) => Promise<boolean>;
  nextDemoObservation: () => Promise<boolean>;
}

/**
 * Loads an inspection with its timeline, observations and tool calls, and
 * exposes the mutations the workspace needs.
 *
 * Every mutation re-reads the whole bundle rather than patching local state:
 * one round trip more, but the panel can never show a state the server does not
 * agree with — which matters when the server has just moved the state machine.
 */
export function useInspection(inspectionId: string | undefined): InspectionController {
  const [actionError, setActionError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const loader = useCallback(async (): Promise<InspectionBundle> => {
    if (!inspectionId) throw new Error("No inspection was selected.");
    const [inspection, timeline, observations, toolCalls] = await Promise.all([
      api.getInspection(inspectionId),
      api.timeline(inspectionId),
      api.observations(inspectionId),
      api.toolCalls(inspectionId)
    ]);
    return { inspection, timeline, observations, toolCalls };
  }, [inspectionId]);

  const state = useAsync(loader, [loader]);

  const withRefresh = useCallback(
    async (work: () => Promise<unknown>): Promise<boolean> => {
      setPending(true);
      setActionError(null);
      try {
        await work();
        await state.reload();
        return true;
      } catch (error) {
        setActionError(messageOf(error));
        return false;
      } finally {
        setPending(false);
      }
    },
    [state]
  );

  const decide = useCallback(
    async (approved: boolean, note: string): Promise<Incident | null> => {
      if (!inspectionId) return null;
      setPending(true);
      setActionError(null);
      try {
        const incident = approved
          ? await api.approve(inspectionId, note)
          : await api.reject(inspectionId, note);
        await state.reload();
        return incident;
      } catch (error) {
        setActionError(messageOf(error));
        return null;
      } finally {
        setPending(false);
      }
    },
    [inspectionId, state]
  );

  const controller = useMemo<InspectionController>(
    () => ({
      bundle: state.data,
      loading: state.loading,
      error: state.error,
      actionError,
      pending,
      reload: state.reload,
      upload: (file: File) => withRefresh(() => api.uploadImage(inspectionId as string, file)),
      sendMessage: (content: string) =>
        withRefresh(() => api.sendMessage(inspectionId as string, content)),
      analyze: () => withRefresh(() => api.analyzeInspection(inspectionId as string)),
      decide,
      resolve: (resolved: boolean) =>
        withRefresh(() => api.resolve(inspectionId as string, resolved)),
      nextDemoObservation: () => withRefresh(() => api.nextDemoObservation(inspectionId as string))
    }),
    [state.data, state.loading, state.error, state.reload, actionError, pending, withRefresh, decide, inspectionId]
  );

  return controller;
}

/** The newest observation that has an analysis attached. */
export function latestAnalysed(bundle: InspectionBundle | null): Observation | null {
  if (!bundle) return null;
  const analysed = bundle.observations.filter((observation) => observation.analysis !== null);
  return analysed.length > 0 ? analysed[analysed.length - 1] : null;
}
