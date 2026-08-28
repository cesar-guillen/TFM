import { useEffect, useRef, useState } from "react";
import {
  ingestPdf,
  type IngestStarted,
  type ReportType,
  type VerdictMode,
  type VerifyMode,
} from "../api/client";

const REPORT_TYPE_HINTS: Record<ReportType, string> = {
  incident:
    "A write-up of an intrusion that actually happened — maps what the attacker was observed doing.",
  pentest:
    "A penetration-test / red-team report — maps what the testers did (first-person narration counts); vulnerabilities noted but not exploited are not mapped.",
};

const VERIFY_MODE_HINTS: Record<VerifyMode, string> = {
  off: "Every technique the model maps is kept as-is. Fastest.",
  demote:
    "Each mapped technique is double-checked; low-confidence ones stay in the matrix, scored near zero and outlined in yellow, so you can review them yourself.",
  drop: "Each mapped technique is double-checked; low-confidence ones are removed outright. Fewest false positives, but can lose weakly-evidenced real techniques.",
};

const VERDICT_MODE_HINTS: Record<VerdictMode, string> = {
  menu: "All candidate techniques of a passage are judged in one model call. The default.",
  independent:
    "Each candidate technique is judged on its own — slightly better recall and identical results run-to-run, but can raise false positives on some reports and takes ~1.5× longer.",
};

// The options we steer users toward. Strict (drop) measured best on exact F1
// in the eval harness (2026-08-22: mean 0.551 → 0.615 across the three
// labelled reports, false positives roughly halved) and was the recommended
// default for that reason — but silently dropping a low-confidence finding
// means a real technique can vanish with nothing to notice. Balanced (demote)
// became the recommendation on 2026-08-28 at the user's explicit request:
// nothing is removed, low-confidence findings are just outlined in yellow in
// the matrix so the reviewer sees exactly what to double-check. Keep this in
// sync with `verify_mode` in backend/app/core/config.py. Report type has no
// recommendation — it depends on the document.
const RECOMMENDED_VERIFY: VerifyMode = "demote";
const RECOMMENDED_VERDICT: VerdictMode = "menu";

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

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
  /** Report-kind picker (incident vs pentest), same ownership pattern. */
  reportType?: ReportType;
  onReportTypeChange?: (value: ReportType) => void;
}

export default function UploadPanel({
  onStarted,
  variant = "hero",
  verifyMode = "demote",
  onVerifyModeChange,
  verdictMode = "menu",
  onVerdictModeChange,
  reportType = "incident",
  onReportTypeChange,
}: UploadPanelProps) {
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  // Picking a file no longer uploads immediately: it's staged here and a
  // dialog opens over the page to confirm the run's options (report kind +
  // the mapping toggles) before anything is sent to the backend.
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function stageFile(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    setError("");
    setPendingFile(file);
    // Reset the input so cancelling and re-picking the same file re-fires
    // onChange (a same-value change event is otherwise swallowed).
    if (inputRef.current) inputRef.current.value = "";
  }

  function cancelPending() {
    if (loading) return; // the upload is already in flight
    setPendingFile(null);
    setError("");
  }

  async function startUpload() {
    if (!pendingFile) return;
    setLoading(true);
    setError("");
    try {
      const result = await ingestPdf(pendingFile);
      setPendingFile(null);
      onStarted(result);
    } catch (err) {
      // Keep the dialog open so the user can retry or cancel.
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  // Escape closes the dialog (unless the upload is already in flight).
  useEffect(() => {
    if (!pendingFile) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") cancelPending();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingFile, loading]);

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
          stageFile(e.dataTransfer.files);
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
          onChange={(e) => stageFile(e.target.files)}
          style={{ display: "none" }}
        />
      </div>

      {error && !pendingFile && (
        <div className="badge badge-danger" style={{ width: "fit-content" }}>
          {error}
        </div>
      )}

      {pendingFile && (
        <div className="uploader-modal" onClick={cancelPending} role="presentation">
          <div
            className="uploader-modal__card"
            role="dialog"
            aria-modal="true"
            aria-label="Configure this mapping run"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="uploader-modal__header">
              <h3 className="uploader-modal__title">Configure this run</h3>
              <span className="uploader-modal__file" title={pendingFile.name}>
                {pendingFile.name} · {formatSize(pendingFile.size)}
              </span>
            </div>

            {onReportTypeChange && (
              <div className="uploader__option">
                <div className="uploader__option-row">
                  <span className="uploader__option-title">
                    <strong>Report type</strong>
                  </span>
                  <div className="uploader__modes" role="radiogroup" aria-label="Report type">
                    {(["incident", "pentest"] as ReportType[]).map((mode) => (
                      <button
                        key={mode}
                        type="button"
                        role="radio"
                        aria-checked={reportType === mode}
                        className={`uploader__mode${reportType === mode ? " uploader__mode--active" : ""}`}
                        onClick={() => onReportTypeChange(mode)}
                      >
                        {mode === "incident" ? "Incident report" : "Pentest report"}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="uploader__option-hint">{REPORT_TYPE_HINTS[reportType]}</div>
              </div>
            )}

            {onVerifyModeChange && (
              <div className="uploader__option">
                <div className="uploader__option-row">
                  <span className="uploader__option-title">
                    <strong>Remove low-confidence findings</strong>
                    <span className="uploader__rec-pill">Recommended: Balanced</span>
                  </span>
                  <div className="uploader__modes" role="radiogroup" aria-label="Remove low-confidence findings">
                    {(["off", "demote", "drop"] as VerifyMode[]).map((mode) => (
                      <button
                        key={mode}
                        type="button"
                        role="radio"
                        aria-checked={verifyMode === mode}
                        title={mode === RECOMMENDED_VERIFY ? "Recommended" : undefined}
                        className={
                          `uploader__mode${verifyMode === mode ? " uploader__mode--active" : ""}` +
                          (mode === RECOMMENDED_VERIFY ? " uploader__mode--recommended" : "")
                        }
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

            {onVerdictModeChange && (
              <div className="uploader__option">
                <div className="uploader__option-row">
                  <span className="uploader__option-title">
                    <strong>Technique judging</strong>
                    <span className="uploader__rec-pill">Recommended: Grouped</span>
                  </span>
                  <div className="uploader__modes" role="radiogroup" aria-label="Technique judging">
                    {(["menu", "independent"] as VerdictMode[]).map((mode) => (
                      <button
                        key={mode}
                        type="button"
                        role="radio"
                        aria-checked={verdictMode === mode}
                        title={mode === RECOMMENDED_VERDICT ? "Recommended" : undefined}
                        className={
                          `uploader__mode${verdictMode === mode ? " uploader__mode--active" : ""}` +
                          (mode === RECOMMENDED_VERDICT ? " uploader__mode--recommended" : "")
                        }
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

            {error && (
              <div className="badge badge-danger" style={{ width: "fit-content" }}>
                {error}
              </div>
            )}

            <div className="uploader-modal__actions">
              <button type="button" className="btn" onClick={cancelPending} disabled={loading}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" onClick={() => void startUpload()} disabled={loading}>
                {loading ? "Uploading…" : "Upload & generate"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
