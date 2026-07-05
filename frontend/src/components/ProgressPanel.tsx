import type { IngestStatus, IngestStatusValue } from "../api/client";

interface ProgressPanelProps {
  job: IngestStatus | null;
}

const STEPS: { key: IngestStatusValue; label: string }[] = [
  { key: "parsing", label: "Extracting text" },
  { key: "chunking", label: "Chunking sections" },
  { key: "embedding", label: "Embedding chunks" },
  { key: "done", label: "Indexed" },
];

const STEP_ORDER = STEPS.map((s) => s.key);

export default function ProgressPanel({ job }: ProgressPanelProps) {
  if (!job) {
    return (
      <>
        <div className="panel-header">
          <h2>Progress</h2>
        </div>
        <div className="panel-body">
          <div className="empty-state">
            <svg width="34" height="34" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.4" />
              <path d="M12 7v5l3.2 2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
            </svg>
            <h3>Nothing processing</h3>
            <p>Upload a report to see each ingestion step here as it runs.</p>
          </div>
        </div>
      </>
    );
  }

  if (job.status === "error") {
    return (
      <>
        <div className="panel-header">
          <h2>Progress</h2>
        </div>
        <div className="panel-body">
          <div className="empty-state">
            <span className="badge badge-danger">Failed</span>
            <h3>{job.filename}</h3>
            <p>{job.error}</p>
          </div>
        </div>
      </>
    );
  }

  const currentIndex = STEP_ORDER.indexOf(job.status);
  const embeddingStarted = job.chunk_count > 0 || job.status === "embedding";
  const embeddingPct = job.chunk_count > 0 ? Math.round((job.chunks_embedded / job.chunk_count) * 100) : 0;

  return (
    <>
      <div className="panel-header" style={{ justifyContent: "space-between" }}>
        <h2>Progress</h2>
        <span className="report-panel__filename">{job.filename}</span>
      </div>
      <div className="panel-body">
        <div className="progress-steps">
          {STEPS.map((step, i) => {
            const state = job.status === "done" ? "done" : i < currentIndex ? "done" : i === currentIndex ? "active" : "pending";
            return (
              <div key={step.key} className={`progress-step progress-step--${state}`}>
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
      </div>
    </>
  );
}
