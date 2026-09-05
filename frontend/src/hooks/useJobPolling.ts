import { useEffect, useRef, useState } from "react";
import {
  getIngestStatus,
  getMappingStatus,
  HttpError,
  isTerminal,
  type IngestStatus,
  type MappingStatus,
} from "../api/client";

const INGEST_POLL_MS = 1000;
// Mapping is minutes-slow (one LLM call per chunk on CPU), so poll gently.
const MAPPING_POLL_MS = 2000;

/** Polls a backend job's status endpoint until it reaches a terminal state,
 * `reportId` changes, or the component unmounts.
 *
 * `onGone` fires if the endpoint 404s — the job no longer exists server-side,
 * e.g. a restored session whose backend has since restarted and lost its
 * in-memory registry. Polling then stops instead of retrying a 404 forever, so
 * the caller can drop the stale session. Other failures back off and retry.
 *
 * Bump `attempt` to restart polling for the same report (a retry after an
 * error, where polling has already stopped and `reportId` alone would not
 * change).
 */
function usePolledJob<T extends { status: string }>(
  reportId: string | null,
  fetchStatus: (reportId: string) => Promise<T>,
  intervalMs: number,
  onGone?: () => void,
  attempt = 0,
): T | null {
  const [job, setJob] = useState<T | null>(null);
  // Kept in a ref so a fresh onGone identity each render doesn't restart polling.
  const onGoneRef = useRef(onGone);
  onGoneRef.current = onGone;

  useEffect(() => {
    setJob(null);
    if (!reportId) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function poll(id: string) {
      try {
        const status = await fetchStatus(id);
        if (cancelled) return;
        setJob(status);
        if (!isTerminal(status.status)) {
          timer = setTimeout(() => poll(id), intervalMs);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof HttpError && err.status === 404) {
          onGoneRef.current?.();
          return;
        }
        timer = setTimeout(() => poll(id), intervalMs * 2);
      }
    }
    poll(reportId);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [reportId, attempt, fetchStatus, intervalMs]);

  return job;
}

/** Ingest progress (parse -> chunk -> embed) for the report being processed. */
export function useIngestJob(reportId: string | null, onGone?: () => void): IngestStatus | null {
  return usePolledJob(reportId, getIngestStatus, INGEST_POLL_MS, onGone);
}

/** Mapping progress for a report whose mapping run has been started; pass null
 * until then. */
export function useMappingJob(
  reportId: string | null,
  attempt = 0,
  onGone?: () => void,
): MappingStatus | null {
  return usePolledJob(reportId, getMappingStatus, MAPPING_POLL_MS, onGone, attempt);
}
