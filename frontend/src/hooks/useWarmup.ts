import { useEffect, useState } from "react";
import { getWarmupStatus, type WarmupStatus } from "../api/client";

const POLL_INTERVAL_MS = 2000;

/** Polls the backend's LLM warm-up state while `active` (i.e. while a
 * pipeline run the user is watching could be waiting on a model load).
 * Polls for as long as `active`, even after seeing "ready": under the CPU
 * profiles' keep-alive the model is evicted between runs and re-warmed
 * during ingest, so the state legitimately regresses to "loading" mid-run —
 * stopping at the first "ready" left the panel blind to that. */
export function useWarmup(active: boolean): WarmupStatus | null {
  const [state, setState] = useState<WarmupStatus | null>(null);

  useEffect(() => {
    if (!active) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function poll() {
      try {
        const status = await getWarmupStatus();
        if (cancelled) return;
        setState(status);
      } catch {
        // Backend briefly unreachable — keep trying while active.
      }
      timer = setTimeout(poll, POLL_INTERVAL_MS);
    }
    poll();

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [active]);

  return state;
}
