import { useRef, useState, type DragEvent, type ReactNode } from "react";

import { api } from "../lib/api";
import { relativeTime } from "../lib/format";
import type { Observation } from "../lib/types";
import { ErrorNote, Spinner } from "./Common";

export function EvidenceViewer({
  inspectionId,
  observations,
  selectedId,
  onSelect
}: {
  inspectionId: string;
  observations: Observation[];
  selectedId: string | null;
  onSelect: (imageId: string) => void;
}) {
  const [annotated, setAnnotated] = useState(true);
  const [failed, setFailed] = useState(false);
  const selected = observations.find((observation) => observation.image_id === selectedId) ?? null;

  if (observations.length === 0) {
    return (
      <div className="grid h-64 place-items-center rounded-lg border border-dashed border-mist bg-mist/20 p-6 text-center text-sm text-slate">
        No image yet. Upload a photograph to begin the inspection.
      </div>
    );
  }

  return (
    <div>
      {observations.length > 1 ? (
        <div className="mb-3 flex flex-wrap gap-2" role="tablist" aria-label="Observations">
          {observations.map((observation) => {
            const isSelected = observation.image_id === selectedId;
            return (
              <button
                key={observation.image_id}
                type="button"
                role="tab"
                aria-selected={isSelected}
                onClick={() => {
                  setFailed(false);
                  onSelect(observation.image_id);
                }}
                className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
                  isSelected
                    ? "border-brand bg-brand text-white"
                    : "border-mist bg-white text-slate hover:bg-mist/40"
                }`}
              >
                Observation {observation.sequence}
              </button>
            );
          })}
        </div>
      ) : null}

      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="inline-flex overflow-hidden rounded-lg border border-mist" role="group" aria-label="Evidence overlay">
          <button
            type="button"
            onClick={() => {
              setFailed(false);
              setAnnotated(true);
            }}
            aria-pressed={annotated}
            className={`min-h-[36px] px-3 text-xs font-semibold ${
              annotated ? "bg-navy text-white" : "bg-white text-slate hover:bg-mist/40"
            }`}
          >
            Annotated
          </button>
          <button
            type="button"
            onClick={() => {
              setFailed(false);
              setAnnotated(false);
            }}
            aria-pressed={!annotated}
            className={`min-h-[36px] px-3 text-xs font-semibold ${
              !annotated ? "bg-navy text-white" : "bg-white text-slate hover:bg-mist/40"
            }`}
          >
            Original
          </button>
        </div>

        {selected ? (
          <p className="text-[11px] text-slate">
            {selected.original_name ?? "upload"} · {relativeTime(selected.created_at)}
            {selected.analysis
              ? ` · OpenCV ${selected.analysis.opencv_version} · ${selected.analysis.latency_ms.toFixed(0)} ms`
              : ""}
          </p>
        ) : null}
      </div>

      {selected ? (
        failed ? (
          <ErrorNote
            message={
              annotated
                ? "The annotated overlay is not available yet. Switch to Original, or run the analysis again."
                : "This evidence image could not be displayed."
            }
          />
        ) : (
          <figure className="overflow-hidden rounded-lg border border-mist bg-navy-deep">
            <img
              key={`${selected.image_id}-${annotated}`}
              src={api.evidenceUrl(inspectionId, selected.image_id, annotated)}
              alt={
                annotated
                  ? "Equipment photograph with OpenCV annotations: detected regions, gauge needle and indicator states"
                  : "The original equipment photograph as uploaded"
              }
              onError={() => setFailed(true)}
              className="block max-h-[520px] w-full object-contain"
            />
          </figure>
        )
      ) : null}

      {selected?.analysis?.quality.requires_new_view ? (
        <div className="mt-3 rounded-lg border border-amber/40 bg-amber/10 px-3 py-2 text-sm text-amber-dark">
          <p className="font-semibold">Reinspection advised</p>
          <p>{selected.analysis.quality.reason}</p>
        </div>
      ) : null}

      {selected?.analysis ? (
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] text-slate sm:grid-cols-4">
          <div>
            <dt className="uppercase tracking-wide">Blur</dt>
            <dd className="font-mono text-navy">{selected.analysis.quality.blur_score.toFixed(2)}</dd>
          </div>
          <div>
            <dt className="uppercase tracking-wide">Exposure</dt>
            <dd className="font-mono text-navy">
              {selected.analysis.quality.exposure_quality.toFixed(2)}
            </dd>
          </div>
          <div>
            <dt className="uppercase tracking-wide">Resolution</dt>
            <dd className="font-mono text-navy">
              {selected.analysis.quality.width}×{selected.analysis.quality.height}
            </dd>
          </div>
          <div>
            <dt className="uppercase tracking-wide">Preprocessing</dt>
            <dd className="font-mono text-navy">
              {selected.analysis.preprocessing.length > 0
                ? selected.analysis.preprocessing.join(", ")
                : "none"}
            </dd>
          </div>
        </dl>
      ) : null}
    </div>
  );
}

export function UploadPanel({
  onUpload,
  pending,
  error,
  problemStatement,
  onProblemChange,
  showProblem,
  children
}: {
  onUpload: (file: File) => void | Promise<unknown>;
  pending: boolean;
  error: string | null;
  problemStatement?: string;
  onProblemChange?: (value: string) => void;
  showProblem?: boolean;
  children?: ReactNode;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [dragging, setDragging] = useState(false);

  function handleFiles(files: FileList | null) {
    const file = files?.[0];
    if (file) void onUpload(file);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    handleFiles(event.dataTransfer.files);
  }

  return (
    <div className="space-y-3">
      {showProblem && onProblemChange ? (
        <div>
          <label htmlFor="problem" className="block text-sm font-semibold text-ink">
            What is happening?
          </label>
          <textarea
            id="problem"
            value={problemStatement ?? ""}
            onChange={(event) => onProblemChange(event.target.value)}
            rows={3}
            placeholder="For example: the dishwasher is switched on but nothing happens when I press start."
            className="mt-1 w-full rounded-lg border border-mist px-3 py-2 text-base focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30"
          />
        </div>
      ) : null}

      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`rounded-lg border-2 border-dashed p-4 text-center transition ${
          dragging ? "border-brand bg-brand-pale" : "border-mist bg-mist/20"
        }`}
      >
        <p className="text-sm text-slate">
          Drag a photograph here, or choose one from your device.
        </p>
        <label
          htmlFor="image-upload"
          className="mt-3 inline-flex min-h-[44px] cursor-pointer items-center justify-center rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-navy focus-within:ring-2 focus-within:ring-brand-light"
        >
          {pending ? "Analysing…" : "Choose or take a photograph"}
        </label>
        <input
          ref={inputRef}
          id="image-upload"
          type="file"
          accept="image/*"
          capture="environment"
          className="sr-only"
          onChange={(event) => handleFiles(event.target.files)}
        />
        <p className="mt-2 text-[11px] text-slate">
          JPEG, PNG or WebP, up to 12 MiB. The original is stored unchanged; annotations are kept
          separately.
        </p>
      </div>

      {pending ? <Spinner label="Measuring the image with OpenCV…" /> : null}
      {error ? <ErrorNote message={error} /> : null}
      {children}
    </div>
  );
}
