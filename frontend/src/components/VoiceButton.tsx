import { useState } from "react";

import type { VoiceController } from "../hooks/useVoice";

const buttonBase =
  "inline-flex min-h-[40px] items-center gap-1.5 rounded-lg border px-3 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:opacity-60";

/**
 * Voice playback for one piece of guidance.
 *
 * Written guidance is always rendered by the parent, so a failure here can only
 * ever remove the audio — never the instructions.
 */
export function VoiceControl({
  voice,
  text,
  compact = false
}: {
  voice: VoiceController;
  text: string;
  compact?: boolean;
}) {
  const [expandedError, setExpandedError] = useState(false);
  const busy = voice.phase === "loading";
  const playing = voice.phase === "playing";

  if (!voice.available && !voice.error) {
    return compact ? null : (
      <p className="text-xs text-slate">
        Voice guidance is not configured on this deployment. The written guidance above is complete.
      </p>
    );
  }

  return (
    <div className={compact ? "mt-2" : "mt-3"}>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className={`${buttonBase} border-brand/30 bg-brand-pale text-navy hover:bg-brand/10`}
          onClick={() => (playing || voice.phase === "paused" ? voice.toggle() : void voice.speak(text))}
          disabled={busy}
          aria-label={playing ? "Pause spoken guidance" : "Play spoken guidance"}
        >
          {busy ? (
            <>
              <span
                aria-hidden="true"
                className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-brand/30 border-t-brand"
              />
              Preparing audio…
            </>
          ) : playing ? (
            <>❚❚ Pause</>
          ) : voice.phase === "paused" ? (
            <>▶ Resume</>
          ) : (
            <>🔊 Listen</>
          )}
        </button>

        <button
          type="button"
          className={`${buttonBase} border-mist bg-white text-navy hover:bg-mist/40`}
          onClick={() => void voice.replay()}
          disabled={busy || !voice.loadedText}
          aria-label="Replay spoken guidance"
        >
          ↻ Replay
        </button>

        <button
          type="button"
          className={`${buttonBase} border-mist bg-white text-navy hover:bg-mist/40`}
          onClick={voice.toggleMute}
          aria-pressed={voice.muted}
          aria-label={voice.muted ? "Unmute voice guidance" : "Mute voice guidance"}
        >
          {voice.muted ? "🔇 Muted" : "🔊 Sound on"}
        </button>

        {voice.phase !== "idle" ? (
          <button
            type="button"
            className={`${buttonBase} border-mist bg-white text-slate hover:bg-mist/40`}
            onClick={voice.stop}
          >
            ■ Stop
          </button>
        ) : null}
      </div>

      {voice.error ? (
        <div className="mt-2">
          <button
            type="button"
            onClick={() => setExpandedError((value) => !value)}
            className="text-xs font-medium text-amber-dark underline"
            aria-expanded={expandedError}
          >
            {expandedError ? "Hide voice error" : "Voice guidance is unavailable — details"}
          </button>
          {expandedError ? (
            <p className="mt-1 text-xs text-slate">{voice.error}</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
