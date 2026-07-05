import { useState } from "react";
import UploadPanel, { type IngestResult } from "./UploadPanel";

interface ReportPanelProps {
  report: IngestResult;
  onUploaded: (result: IngestResult) => void;
}

export default function ReportPanel({ report, onUploaded }: ReportPanelProps) {
  const [showText, setShowText] = useState(false);

  return (
    <div className="report-panel">
      <div className="panel-header" style={{ justifyContent: "space-between" }}>
        <h2>Report</h2>
        <button className="btn" style={{ padding: "0.25rem 0.55rem", fontSize: "0.75rem" }} onClick={() => setShowText((v) => !v)}>
          {showText ? "Hide text" : "View extracted text"}
        </button>
      </div>
      <div className="report-panel__body">
        <div className="report-panel__current">
          <span className="badge">Loaded</span>
          <span className="report-panel__filename">{report.filename}</span>
        </div>

        {showText ? (
          <pre className="report-panel__text">{report.markdown}</pre>
        ) : (
          <UploadPanel variant="compact" onUploaded={onUploaded} />
        )}
      </div>
    </div>
  );
}
