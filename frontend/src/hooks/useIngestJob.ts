import { useEffect, useState } from "react";
import { getIngestStatus, type IngestStatus } from "../api/client";

const POLL_INTERVAL_MS = 1000;

/** Polls ingest status while a report is being processed; stops once it reaches
 * a terminal state ("done" or "error"), or if `reportId` changes/unmounts. */
export function useIngestJob(reportId: string | null): IngestStatus | null {
  const [job, setJob] = useState<IngestStatus | null>(null);

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
      } catch {
        if (!cancelled) timer = setTimeout(poll, POLL_INTERVAL_MS * 2);
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
