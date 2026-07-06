import { useEffect, useRef } from "react";
import type { IngestStatus, IngestStatusValue, MappingStatus } from "../api/client";

interface ProgressPanelProps {
  job: IngestStatus | null;
  mappingJob: MappingStatus | null;
  /** Retry hook for a failed run — mapping starts automatically otherwise. */
  onGenerate: () => void;
  generateDisabled?: boolean;
}

const STEPS: { key: IngestStatusValue; label: string }[] = [
  { key: "parsing", label: "Extracting text" },
  { key: "chunking", label: "Chunking sections" },
  { key: "embedding", label: "Embedding chunks" },
  { key: "done", label: "Indexed" },
];

const STEP_ORDER = STEPS.map((s) => s.key);

const MAPPING_LABELS: Record<MappingStatus["status"], string> = {
  retrieving: "Retrieving candidate techniques…",
  mapping: "Mapping chunks with the LLM…",
  aggregating: "Aggregating techniques…",
  done: "Matrix generated",
  error: "Mapping failed",
};

function MappingSection({
  mappingJob,
  onGenerate,
  generateDisabled,
}: ProgressPanelProps) {
  // Only reachable once ingest is done. Mapping auto-starts from the
  // dashboard, so before the first status poll lands there's just a beat of
  // "starting" — no button.
  if (!mappingJob) {
    return (
      <div className="mapping-section">
        <span className="badge badge-accent">Starting technique mapping…</span>
        <p className="mapping-section__hint">
          Each indexed chunk is mapped to ATT&amp;CK techniques with the local LLM — results appear in the matrix
          above as they come in.
        </p>
      </div>
    );
  }

  if (mappingJob.status === "error") {
    return (
      <div className="mapping-section">
        <span className="badge badge-danger">Failed</span>
        <p className="mapping-section__hint">{mappingJob.error}</p>
        <button className="btn" onClick={onGenerate}>
          Retry
        </button>
      </div>
    );
  }

  const pct = mappingJob.chunk_count > 0 ? Math.round((mappingJob.chunks_mapped / mappingJob.chunk_count) * 100) : 0;
  return (
    <div className="mapping-section">
      <div className="mapping-section__status">
        <span className={`badge${mappingJob.status === "done" ? "" : " badge-accent"}`}>
          {MAPPING_LABELS[mappingJob.status]}
        </span>
        {mappingJob.status === "done" && mappingJob.layer && (
          <span className="mapping-section__count">{mappingJob.layer.techniques.length} techniques</span>
        )}
      </div>
      {(mappingJob.status === "mapping" || mappingJob.status === "aggregating") && (
        <>
          <div className="progress-step__bar">
            <div className="progress-step__bar-fill" style={{ width: `${pct}%` }} />
          </div>
          <span className="progress-step__meta">
            {mappingJob.chunks_mapped} / {mappingJob.chunk_count} chunks mapped
          </span>
        </>
      )}
    </div>
  );
}

export default function ProgressPanel({ job, mappingJob, onGenerate, generateDisabled }: ProgressPanelProps) {
  const bodyRef = useRef<HTMLDivElement>(null);

  // Keep the step the pipeline is currently on in view: whenever ingest or
  // mapping advances, scroll the active element into the panel's viewport
  // (the panel body scrolls, not the page).
  useEffect(() => {
    bodyRef.current
      ?.querySelector("[data-progress-active]")
      ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [job?.status, mappingJob?.status]);

  if (!job) {
    return <p className="mapping-section__hint">Waiting for the upload to register…</p>;
  }

  if (job.status === "error") {
    return (
      <div className="mapping-section">
        <span className="badge badge-danger">Failed</span>
        <p className="mapping-section__hint">{job.error}</p>
      </div>
    );
  }

  const currentIndex = STEP_ORDER.indexOf(job.status);
  const embeddingStarted = job.chunk_count > 0 || job.status === "embedding";
  const embeddingPct = job.chunk_count > 0 ? Math.round((job.chunks_embedded / job.chunk_count) * 100) : 0;

  return (
    <div ref={bodyRef}>
      <div className="progress-steps">
        {STEPS.map((step, i) => {
          const state = job.status === "done" ? "done" : i < currentIndex ? "done" : i === currentIndex ? "active" : "pending";
          return (
            <div
              key={step.key}
              className={`progress-step progress-step--${state}`}
              data-progress-active={state === "active" ? "" : undefined}
            >
              <span className="progress-step__dot" />
              <div className="progress-step__body">
                <span className="progress-step__label">{step.label}</span>
                {step.key === "embedding" && embeddingStarted && (
                  <>
                    <div className="progress-step__bar">
                      <div className="progress-step__bar-fill" style={{ width: `${embeddingPct}%` }} />
                    </div>
                    <span className="progress-step__meta">
                      {job.chunks_embedded} / {job.chunk_count} chunks
                    </span>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {job.status === "done" && (
        <div data-progress-active="">
          <MappingSection job={job} mappingJob={mappingJob} onGenerate={onGenerate} generateDisabled={generateDisabled} />
        </div>
      )}
    </div>
  );
}
