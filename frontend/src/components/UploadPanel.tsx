import { useRef, useState } from "react";
import { ingestPdf, type IngestStarted } from "../api/client";

interface UploadPanelProps {
  onStarted: (result: IngestStarted) => void;
  variant?: "hero" | "compact";
}

export default function UploadPanel({ onStarted, variant = "hero" }: UploadPanelProps) {
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleFiles(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;

    setLoading(true);
    setError("");
    try {
      const result = await ingestPdf(file);
      onStarted(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  const compact = variant === "compact";

  return (
    <div className={`uploader${compact ? " uploader--compact" : ""}`}>
      <div
        className={`uploader__dropzone${dragOver ? " uploader__dropzone--over" : ""}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          handleFiles(e.dataTransfer.files);
        }}
      >
        <svg
          width={compact ? 22 : 30}
          height={compact ? 22 : 30}
          viewBox="0 0 24 24"
          fill="none"
          style={{ margin: compact ? "0 auto 0.4rem" : "0 auto 0.7rem", display: "block" }}
        >
          <path
            d="M12 16V4m0 0L7 9m5-5l5 5"
            stroke="var(--text-dim)"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"
            stroke="var(--text-dim)"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <div className="uploader__title">
          {compact ? "Upload another report" : "Drop a PDF here, or click to browse"}
        </div>
        {!compact && (
          <div className="uploader__hint">Incident reports, pentest results, security policies</div>
        )}
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          onChange={(e) => handleFiles(e.target.files)}
          style={{ display: "none" }}
        />
      </div>

      {loading && (
        <div className="uploader__status">
          <span className="badge">Uploading</span>
          Sending to the server…
        </div>
      )}

      {error && (
        <div className="badge badge-danger" style={{ width: "fit-content" }}>
          {error}
        </div>
      )}
    </div>
  );
}
