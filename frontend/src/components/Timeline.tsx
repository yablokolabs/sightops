import { useEffect, useRef } from "react";

import { clockTime, relativeTime } from "../lib/format";
import type { TimelineEntry, TimelineKind } from "../lib/types";
import { DemoChip, ErrorNote, Spinner, StateChip } from "./Common";
import { VoiceControl } from "./VoiceButton";
import type { VoiceController } from "../hooks/useVoice";

interface KindStyle {
  dot: string;
  label: string;
}

const KIND_STYLES: Record<TimelineKind, KindStyle> = {
  observation: { dot: "bg-brand", label: "Observation" },
  measurement: { dot: "bg-brand-light", label: "Measurement" },
  reasoning: { dot: "bg-navy", label: "Reasoning" },
  tool_call: { dot: "bg-slate", label: "Tool call" },
  tool_result: { dot: "bg-good", label: "Tool result" },
  decision: { dot: "bg-amber", label: "Decision" },
  request: { dot: "bg-amber", label: "Request" },
  user_message: { dot: "bg-brand", label: "You" },
  incident: { dot: "bg-bad", label: "Incident" },
  approval: { dot: "bg-good", label: "Approval" },
  error: { dot: "bg-bad", label: "Error" }
};

function isDeterministic(entry: TimelineEntry): boolean {
  return entry.data["policy"] === "deterministic_demo" || entry.title.startsWith("DEMO MODE");
}

function toolOf(entry: TimelineEntry): string | null {
  const tool = entry.data["tool"];
  return typeof tool === "string" ? tool : null;
}

export function Timeline({
  entries,
  loading,
  error,
  voice
}: {
  entries: TimelineEntry[];
  loading: boolean;
  error: string | null;
  voice: VoiceController;
}) {
  const bottom = useRef<HTMLDivElement | null>(null);

  // Follow the investigation as it grows. Scrolling the container (not the page)
  // keeps the viewer's own scroll position on the evidence intact.
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest" });
  }, [entries.length]);

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto pr-1" aria-live="polite" aria-busy={loading}>
        {loading && entries.length === 0 ? (
          <Spinner label="Loading the investigation…" />
        ) : null}
        {error ? <ErrorNote message={error} /> : null}
        {!loading && entries.length === 0 && !error ? (
          <p className="text-sm text-slate">
            Nothing has happened yet. Upload a photograph or run a demonstration.
          </p>
        ) : null}

        <ol className="space-y-3">
          {entries.map((entry, index) => {
            const style = KIND_STYLES[entry.kind] ?? { dot: "bg-slate", label: entry.kind };
            const tool = toolOf(entry);
            return (
              <li
                key={entry.id ?? `${entry.kind}-${index}`}
                className="animate-fade-in rounded-lg border border-mist bg-white px-3 py-2"
              >
                <div className="flex items-start gap-2">
                  <span
                    aria-hidden="true"
                    className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${style.dot}`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[10px] font-semibold uppercase tracking-wider text-slate">
                        {style.label}
                      </span>
                      {isDeterministic(entry) ? <DemoChip /> : null}
                      {entry.state ? <StateChip state={entry.state} /> : null}
                      <time
                        className="ml-auto font-mono text-[10px] text-slate/70"
                        dateTime={entry.created_at}
                        title={relativeTime(entry.created_at)}
                      >
                        {clockTime(entry.created_at)}
                      </time>
                    </div>
                    <p className="mt-0.5 text-sm font-semibold text-ink">{entry.title}</p>
                    {tool ? (
                      <p className="mt-0.5 font-mono text-[11px] text-brand">
                        tool: {tool}
                      </p>
                    ) : null}
                    {entry.detail ? (
                      <p className="mt-1 whitespace-pre-wrap text-sm leading-snug text-slate">
                        {entry.detail}
                      </p>
                    ) : null}
                    {entry.kind === "reasoning" ? (
                      <VoiceControl voice={voice} text={entry.detail || entry.title} compact />
                    ) : null}
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
        <div ref={bottom} />
      </div>
    </div>
  );
}
