import { useEffect, useRef } from "react";
import type { IngestStatus, IngestStatusValue, MappingStatus, WarmupStatus } from "../api/client";
import { useWarmup } from "../hooks/useWarmup";

interface ProgressPanelProps {
  job: IngestStatus | null;
  mappingJob: MappingStatus | null;
  /** Retry hook for a failed run — mapping starts automatically otherwise. */
  onGenerate: () => void;
  generateDisabled?: boolean;
  /** Stop the run (ingest or mapping, whichever is active). */
  onCancel?: () => void;
  cancelDisabled?: boolean;
}

/** Warm-up wording matched to the hardware actually in use — the device is
 * only knowable once Ollama has something loaded, so until then stay neutral,
 * and a CPU-only machine never sees "GPU". */
function warmupLabel(warmup: WarmupStatus | null): string {
  if (warmup?.device === "gpu") return "Setting up the GPU — loading the LLM into video memory…";
  if (warmup?.device === "cpu") return "Loading the LLM into memory (CPU mode)…";
  return "Warming up the local LLM…";
}

const STEPS: { key: IngestStatusValue; label: string }[] = [
  { key: "parsing", label: "Extracting text" },
  { key: "chunking", label: "Chunking sections" },
  { key: "embedding", label: "Embedding chunks" },
  { key: "done", label: "Indexed" },
];

const STEP_ORDER = STEPS.map((s) => s.key);

const MAPPING_LABELS: Record<MappingStatus["status"], string> = {
  warming: "Warming up the local LLM…", // replaced by device-aware wording below
  retrieving: "Retrieving candidate techniques…",
  mapping: "Mapping chunks with the LLM…",
  aggregating: "Aggregating techniques…",
  done: "Matrix generated",
  error: "Mapping failed",
  cancelled: "Run cancelled",
};

function MappingSection({
  mappingJob,
  onGenerate,
  generateDisabled,
  warmup,
}: ProgressPanelProps & { warmup: WarmupStatus | null }) {
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

  if (mappingJob.status === "warming") {
    return (
      <div className="mapping-section">
        <span className="badge badge-accent">{warmupLabel(warmup)}</span>
        <p className="mapping-section__hint">
          The model has to be loaded before mapping can start — this happens once, then stays warm.
        </p>
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

export default function ProgressPanel({
  job,
  mappingJob,
  onGenerate,
  generateDisabled,
  onCancel,
  cancelDisabled,
}: ProgressPanelProps) {
  const bodyRef = useRef<HTMLDivElement>(null);

  // Poll the LLM warm-up state while the pipeline is running: it drives the
  // wording of the mapping job's "warming" phase, and lets the user know
  // during ingest that the model is already loading in the background.
  const ingestActive = job !== null && job.status !== "error" && job.status !== "cancelled";
  const pipelineRunning =
    ingestActive &&
    (mappingJob === null ||
      (mappingJob.status !== "done" && mappingJob.status !== "error" && mappingJob.status !== "cancelled"));
  const warmup = useWarmup(pipelineRunning);
  // Cancellable while any stage is still working; pipelineRunning flips false
  // once the mapping job reaches a terminal state.
  const cancellable = pipelineRunning && !(job?.status === "done" && mappingJob?.status === "done");

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

  if (job.status === "cancelled") {
    return (
      <div className="mapping-section">
        <span className="badge">Cancelled</span>
        <p className="mapping-section__hint">The run was stopped before finishing.</p>
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
      {job.status !== "done" && warmup?.status === "loading" && (
        <p className="warmup-note">
          <span className="warmup-note__spinner" aria-hidden="true" />
          {warmupLabel(warmup)} It loads in the background while your report is processed.
        </p>
      )}
      {job.status === "done" && (
        <div data-progress-active="">
          <MappingSection
            job={job}
            mappingJob={mappingJob}
            onGenerate={onGenerate}
            generateDisabled={generateDisabled}
            warmup={warmup}
          />
        </div>
      )}
      {onCancel && cancellable && (
        <button
          className="btn btn-danger progress-cancel"
          onClick={onCancel}
          disabled={cancelDisabled}
          title="Stop this run — nothing is saved for it"
        >
          Cancel run
        </button>
      )}
    </div>
  );
}
