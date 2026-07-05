import { useState } from "react";
import type { IngestStarted, IngestStatus } from "../api/client";
import UploadPanel from "./UploadPanel";

interface ReportPanelProps {
  filename: string;
  job: IngestStatus | null;
  onStarted: (result: IngestStarted) => void;
}

export default function ReportPanel({ filename, job, onStarted }: ReportPanelProps) {
  const [showText, setShowText] = useState(false);
  const markdown = job?.status === "done" ? job.markdown : null;

  return (
    <div className="report-panel">
      <div className="panel-header" style={{ justifyContent: "space-between" }}>
        <h2>Report</h2>
        <button
          className="btn"
          style={{ padding: "0.25rem 0.55rem", fontSize: "0.75rem" }}
          onClick={() => setShowText((v) => !v)}
          disabled={!markdown}
        >
          {showText ? "Hide text" : "View extracted text"}
        </button>
      </div>
      <div className="report-panel__body">
        <div className="report-panel__current">
          <span className="badge">{markdown ? "Loaded" : "Processing…"}</span>
          <span className="report-panel__filename">{filename}</span>
        </div>

        {showText && markdown ? (
          <pre className="report-panel__text">{markdown}</pre>
        ) : (
          <UploadPanel variant="compact" onStarted={onStarted} />
        )}
      </div>
    </div>
  );
}
