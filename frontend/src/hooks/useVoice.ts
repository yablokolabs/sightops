import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import { messageOf } from "./useAsync";

export type VoicePhase = "idle" | "loading" | "playing" | "paused";

export interface VoiceController {
  available: boolean;
  phase: VoicePhase;
  muted: boolean;
  error: string | null;
  /** The text currently loaded into the player, so Replay knows what to re-say. */
  loadedText: string | null;
  speak: (text: string) => Promise<void>;
  toggle: () => void;
  replay: () => Promise<void>;
  stop: () => void;
  toggleMute: () => void;
}

/**
 * Voice guidance.
 *
 * The backend synthesises through ElevenLabs and returns audio bytes; this hook
 * only owns playback. When the provider is unconfigured or the request fails
 * (503/502), `available` goes false and `error` explains it — the written
 * guidance is never blocked by the absence of audio.
 */
export function useVoice(): VoiceController {
  const [available, setAvailable] = useState(false);
  const [phase, setPhase] = useState<VoicePhase>("idle");
  const [muted, setMuted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadedText, setLoadedText] = useState<string | null>(null);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .voiceStatus()
      .then((status) => {
        if (!cancelled) setAvailable(status.configured);
      })
      .catch(() => {
        if (!cancelled) setAvailable(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const release = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
  }, []);

  useEffect(() => release, [release]);

  const speak = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      release();
      setError(null);
      setPhase("loading");
      try {
        const blob = await api.synthesize(trimmed);
        const url = URL.createObjectURL(blob);
        urlRef.current = url;
        const audio = new Audio(url);
        audio.muted = muted;
        audio.onended = () => setPhase("idle");
        audio.onpause = () => setPhase((current) => (current === "playing" ? "paused" : current));
        audio.onplay = () => setPhase("playing");
        audioRef.current = audio;
        setLoadedText(trimmed);
        await audio.play();
        setPhase("playing");
      } catch (caught) {
        release();
        setPhase("idle");
        setError(
          `${messageOf(caught)} Voice guidance is unavailable — the written guidance above is unaffected.`
        );
      }
    },
    [muted, release]
  );

  const toggle = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) {
      void audio.play();
      setPhase("playing");
    } else {
      audio.pause();
      setPhase("paused");
    }
  }, []);

  const replay = useCallback(async () => {
    if (loadedText) {
      await speak(loadedText);
      return;
    }
    const audio = audioRef.current;
    if (audio) {
      audio.currentTime = 0;
      await audio.play();
      setPhase("playing");
    }
  }, [loadedText, speak]);

  const stop = useCallback(() => {
    release();
    setPhase("idle");
  }, [release]);

  const toggleMute = useCallback(() => {
    setMuted((current) => {
      const next = !current;
      if (audioRef.current) audioRef.current.muted = next;
      return next;
    });
  }, []);

  return { available, phase, muted, error, loadedText, speak, toggle, replay, stop, toggleMute };
}
