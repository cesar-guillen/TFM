import { useEffect, useRef, useState } from "react";
import { getMappingStatus, HttpError, type MappingStatus } from "../api/client";

// Mapping is minutes-slow (one LLM call per chunk on CPU), so poll gently.
const POLL_INTERVAL_MS = 2000;

/** Polls mapping status for a report whose mapping job has been started
 * (pass null until then); stops at a terminal state ("done"/"error"), or if
 * `reportId` changes/unmounts. Mirrors useIngestJob. Bump `attempt` to
 * restart polling for the same report (retry after an error — polling has
 * already stopped by then, and `reportId` alone wouldn't change).
 *
 * `onGone` fires on a 404 (the mapping job no longer exists server-side, e.g.
 * a restored session after a backend restart) so the caller can drop the
 * stale session instead of polling a 404 forever. */
export function useMappingJob(
  reportId: string | null,
  attempt = 0,
  onGone?: () => void,
): MappingStatus | null {
  const [job, setJob] = useState<MappingStatus | null>(null);
  const onGoneRef = useRef(onGone);
  onGoneRef.current = onGone;

  useEffect(() => {
    setJob(null);
    if (!reportId) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function poll() {
      try {
        const status = await getMappingStatus(reportId!);
        if (cancelled) return;
        setJob(status);
        if (status.status !== "done" && status.status !== "error" && status.status !== "cancelled") {
          timer = setTimeout(poll, POLL_INTERVAL_MS);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof HttpError && err.status === 404) {
          onGoneRef.current?.();
          return; // job gone — don't keep polling a 404
        }
        timer = setTimeout(poll, POLL_INTERVAL_MS * 2);
      }
    }
    poll();

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [reportId, attempt]);

  return job;
}
