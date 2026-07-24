import { useEffect, useRef, useState } from "react";
import { getIngestStatus, HttpError, type IngestStatus } from "../api/client";

const POLL_INTERVAL_MS = 1000;

/** Polls ingest status while a report is being processed; stops once it reaches
 * a terminal state ("done" or "error"), or if `reportId` changes/unmounts.
 *
 * `onGone` is called if the status endpoint 404s — the job no longer exists
 * server-side (e.g. a restored session whose backend has since restarted and
 * lost its in-memory registry). Polling stops rather than retrying a 404
 * forever, and the caller can drop the stale session. */
export function useIngestJob(reportId: string | null, onGone?: () => void): IngestStatus | null {
  const [job, setJob] = useState<IngestStatus | null>(null);
  // Kept in a ref so a fresh onGone identity each render doesn't restart polling.
  const onGoneRef = useRef(onGone);
  onGoneRef.current = onGone;

  useEffect(() => {
    setJob(null);
    if (!reportId) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function poll() {
      try {
        const status = await getIngestStatus(reportId!);
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
  }, [reportId]);

  return job;
}
