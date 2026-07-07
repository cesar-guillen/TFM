import { useEffect, useState } from "react";
import { getWarmupStatus, type WarmupStatus } from "../api/client";

const POLL_INTERVAL_MS = 2000;

/** Polls the backend's LLM warm-up state while `active` (i.e. while a
 * pipeline run the user is watching could be waiting on a model load).
 * Stops on its own once the model is ready — with OLLAMA_KEEP_ALIVE=-1 it
 * can't regress within a backend's lifetime, and if it does (idle eviction
 * under a keep-alive duration), the mapping job's "warming" status makes the
 * caller pass `active` again. */
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
        if (status.status === "ready") return;
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
