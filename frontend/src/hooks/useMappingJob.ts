import { useEffect, useState } from "react";
import { getMappingStatus, type MappingStatus } from "../api/client";

// Mapping is minutes-slow (one LLM call per chunk on CPU), so poll gently.
const POLL_INTERVAL_MS = 2000;

/** Polls mapping status for a report whose mapping job has been started
 * (pass null until then); stops at a terminal state ("done"/"error"), or if
 * `reportId` changes/unmounts. Mirrors useIngestJob. */
export function useMappingJob(reportId: string | null): MappingStatus | null {
  const [job, setJob] = useState<MappingStatus | null>(null);

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
        if (status.status !== "done" && status.status !== "error") {
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
