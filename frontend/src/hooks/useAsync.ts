import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../lib/api";

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

export interface AsyncResult<T> extends AsyncState<T> {
  /** Re-run the loader, keeping the previous data visible while it refreshes. */
  reload: () => Promise<void>;
  /** Replace the data locally after a mutation returns a fresh value. */
  setData: (value: T) => void;
}

function messageOf(error: unknown): string {
  if (error instanceof ApiError) {
    return error.requestId ? `${error.message} (request ${error.requestId})` : error.message;
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

/**
 * Runs `loader` on mount and whenever its identity changes.
 *
 * Results from a superseded run are discarded, so a slow first request cannot
 * overwrite a fast second one — the classic source of a workspace showing stale
 * evidence after the user uploads a new photograph.
 */
export function useAsync<T>(loader: () => Promise<T>, deps: readonly unknown[]): AsyncResult<T> {
  const [state, setState] = useState<AsyncState<T>>({ data: null, loading: true, error: null });
  const runId = useRef(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback(async () => {
    const id = ++runId.current;
    setState((previous) => ({ ...previous, loading: true, error: null }));
    try {
      const data = await loader();
      if (id !== runId.current || !mounted.current) return;
      setState({ data, loading: false, error: null });
    } catch (error) {
      if (id !== runId.current || !mounted.current) return;
      setState({ data: null, loading: false, error: messageOf(error) });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    void run();
  }, [run]);

  const setData = useCallback((value: T) => {
    setState({ data: value, loading: false, error: null });
  }, []);

  return { ...state, reload: run, setData };
}

/** Tracks a single in-flight action (upload, approve, send) with its own error. */
export function useAction<Args extends unknown[], Result>(
  action: (...args: Args) => Promise<Result>
) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async (...args: Args): Promise<Result | null> => {
      setPending(true);
      setError(null);
      try {
        return await action(...args);
      } catch (caught) {
        setError(messageOf(caught));
        return null;
      } finally {
        setPending(false);
      }
    },
    [action]
  );

  return { run, pending, error, clearError: () => setError(null) };
}

export { messageOf };
