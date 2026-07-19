import { useRef, useState } from "react";
import { ingestPdf, type IngestStarted, type VerdictMode, type VerifyMode } from "../api/client";

const VERIFY_MODE_HINTS: Record<VerifyMode, string> = {
  off: "Every technique the model maps is kept as-is. Fastest.",
  demote:
    "Each mapped technique is double-checked; ones that fail the check stay in the matrix but are scored near zero and marked, so you can review or ignore them.",
  drop: "Each mapped technique is double-checked; ones that fail the check are removed. Fewest false positives, but can lose weakly-evidenced real techniques.",
};

const VERDICT_MODE_HINTS: Record<VerdictMode, string> = {
  menu: "All candidate techniques of a passage are judged in one model call. The default.",
  independent:
    "Each candidate technique is judged on its own — slightly better recall and identical results run-to-run, but can raise false positives on some reports and takes ~1.5× longer.",
};

interface UploadPanelProps {
  onStarted: (result: IngestStarted) => void;
  variant?: "hero" | "compact";
  /** Verification-mode picker (owned by the page — the value is used when
   * the mapping run starts, after ingest finishes). Omit to hide it. */
  verifyMode?: VerifyMode;
  onVerifyModeChange?: (value: VerifyMode) => void;
  /** Verdict-architecture picker, same ownership pattern. Omit to hide it. */
  verdictMode?: VerdictMode;
  onVerdictModeChange?: (value: VerdictMode) => void;
}

export default function UploadPanel({
  onStarted,
  variant = "hero",
  verifyMode = "off",
  onVerifyModeChange,
  verdictMode = "menu",
  onVerdictModeChange,
}: UploadPanelProps) {
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

      {!compact && onVerifyModeChange && (
        <div className="uploader__option">
          <div className="uploader__option-row">
            <strong>False-positive filtering</strong>
            <div className="uploader__modes" role="radiogroup" aria-label="False-positive filtering">
              {(["off", "demote", "drop"] as VerifyMode[]).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  role="radio"
                  aria-checked={verifyMode === mode}
                  className={`uploader__mode${verifyMode === mode ? " uploader__mode--active" : ""}`}
                  onClick={() => onVerifyModeChange(mode)}
                >
                  {mode === "off" ? "Off" : mode === "demote" ? "Balanced" : "Strict"}
                </button>
              ))}
            </div>
          </div>
          <div className="uploader__option-hint">{VERIFY_MODE_HINTS[verifyMode]}</div>
        </div>
      )}

      {!compact && onVerdictModeChange && (
        <div className="uploader__option">
          <div className="uploader__option-row">
            <strong>Technique judging</strong>
            <div className="uploader__modes" role="radiogroup" aria-label="Technique judging">
              {(["menu", "independent"] as VerdictMode[]).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  role="radio"
                  aria-checked={verdictMode === mode}
                  className={`uploader__mode${verdictMode === mode ? " uploader__mode--active" : ""}`}
                  onClick={() => onVerdictModeChange(mode)}
                >
                  {mode === "menu" ? "Grouped" : "Individual"}
                </button>
              ))}
            </div>
          </div>
          <div className="uploader__option-hint">{VERDICT_MODE_HINTS[verdictMode]}</div>
        </div>
      )}

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
