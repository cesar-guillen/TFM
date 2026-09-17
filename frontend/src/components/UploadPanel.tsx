import { useEffect, useRef, useState } from "react";
import {
  ingestPdf,
  type IngestStarted,
  type ReportType,
  type VerdictMode,
  type VerifyMode,
} from "../api/client";
import { useWarmup } from "../hooks/useWarmup";

// Mirrors MAX_UPLOAD_BYTES in the backend's ingest route, so an oversized file
// is refused before it is uploaded rather than after.
const MAX_UPLOAD_MB = 64;

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

type OcrMode = "on" | "off";

const OCR_MODE_HINTS: Record<OcrMode, string> = {
  on: "Screenshots (console output, dashboards, sandbox logs) are OCR'd and included as evidence. Finds more, especially in log/terminal-heavy reports; can add noisy findings on reports dominated by UI screenshots. Adds roughly 15-30s to ingest.",
  off: "Only the report's typeset text is read — screenshots are skipped, same as before this feature existed.",
};

// The options we steer users toward. Strict scores best on the eval harness,
// but dropping a low-confidence finding means a real technique can vanish with
// nothing to notice, so Balanced is recommended instead: nothing is removed,
// low-confidence findings are just outlined for review. Individual became the
// recommended verdict mode 2026-09-05 (moved from Grouped): on the three
// labelled real DFIR Report intrusions, Individual+Balanced beat Grouped+
// Balanced on exact F1 and precision on 3 of 3 reports, directly fixing a
// user-reported miss on AD/Discovery techniques (local group/account
// enumeration, DCSync) under the old default — see verdict_mode in
// backend/app/core/config.py for the full numbers. Keep in sync with the
// backend setting. Report type has no recommendation — it depends on the
// document.
const RECOMMENDED_VERIFY: VerifyMode = "demote";

// Individual is the general recommendation, but it issues one LLM call per
// candidate instead of one per chunk — on a CPU profile, where every call is
// already far slower, that gap compounds into a much longer run for a recall
// gain that matters less when the user is already trading quality for
// hardware compatibility. Grouped is recommended on CPU for that reason; GPU
// (or before the device is known) keeps the general recommendation.
function recommendedVerdictFor(device: "gpu" | "cpu" | null | undefined): VerdictMode {
  return device === "cpu" ? "menu" : "independent";
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** One labelled row of mutually exclusive run options, with a hint line for
 * whichever is selected. */
function OptionPicker<T extends string>({
  title,
  options,
  value,
  onChange,
  hint,
  recommended,
}: {
  title: string;
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  hint: string;
  recommended?: { value: T; label: string };
}) {
  return (
    <div className="uploader__option">
      <div className="uploader__option-row">
        <span className="uploader__option-title">
          <strong>{title}</strong>
          {recommended && <span className="uploader__rec-pill">Recommended: {recommended.label}</span>}
        </span>
        <div className="uploader__modes" role="radiogroup" aria-label={title}>
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={value === option.value}
              title={option.value === recommended?.value ? "Recommended" : undefined}
              className={
                `uploader__mode${value === option.value ? " uploader__mode--active" : ""}` +
                (option.value === recommended?.value ? " uploader__mode--recommended" : "")
              }
              onClick={() => onChange(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>
      <div className="uploader__option-hint">{hint}</div>
    </div>
  );
}

interface UploadPanelProps {
  onStarted: (result: IngestStarted) => void;
  /** Run-option pickers, each owned by the page (the values are used when the
   * mapping run starts, after ingest finishes). Omit a change handler to hide
   * that picker. */
  verifyMode?: VerifyMode;
  onVerifyModeChange?: (value: VerifyMode) => void;
  verdictMode?: VerdictMode;
  onVerdictModeChange?: (value: VerdictMode) => void;
  reportType?: ReportType;
  onReportTypeChange?: (value: ReportType) => void;
  ocrEnabled?: boolean;
  onOcrEnabledChange?: (value: boolean) => void;
}

/** Drop zone for the report PDF. Picking a file stages it and opens a dialog
 * to confirm the run's options; nothing is uploaded until that is confirmed. */
export default function UploadPanel({
  onStarted,
  verifyMode = "demote",
  onVerifyModeChange,
  verdictMode = "menu",
  onVerdictModeChange,
  reportType = "incident",
  onReportTypeChange,
  ocrEnabled = true,
  onOcrEnabledChange,
}: UploadPanelProps) {
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Only polls while this dialog is open — long enough to learn the device
  // for the recommendation below, without polling /api/warmup in the
  // background for the whole time the dashboard sits idle.
  const warmup = useWarmup(pendingFile !== null);
  const recommendedVerdict = recommendedVerdictFor(warmup?.device);

  function stageFile(files: FileList | null) {
    const file = files?.[0];
    // Reset the input so cancelling and re-picking the same file re-fires
    // onChange (a same-value change event is otherwise swallowed).
    if (inputRef.current) inputRef.current.value = "";
    if (!file) return;
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      setError(`That PDF is ${formatSize(file.size)} — the limit is ${MAX_UPLOAD_MB} MB.`);
      return;
    }
    setError("");
    setPendingFile(file);
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
      const result = await ingestPdf(pendingFile, ocrEnabled);
      setPendingFile(null);
      onStarted(result);
    } catch (err) {
      // Keep the dialog open so the user can retry or cancel.
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!pendingFile) return;
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape" || loading) return;
      setPendingFile(null);
      setError("");
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [pendingFile, loading]);

  return (
    <div className="uploader">
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
        <svg width={30} height={30} viewBox="0 0 24 24" fill="none" style={{ margin: "0 auto 0.7rem", display: "block" }}>
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
        <div className="uploader__title">Drop a PDF here, or click to browse</div>
        <div className="uploader__hint">Incident reports, pentest results, security policies</div>
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
              <OptionPicker
                title="Report type"
                options={[
                  { value: "incident", label: "Incident report" },
                  { value: "pentest", label: "Pentest report" },
                ]}
                value={reportType}
                onChange={onReportTypeChange}
                hint={REPORT_TYPE_HINTS[reportType]}
              />
            )}

            {onVerifyModeChange && (
              <OptionPicker
                title="Remove low-confidence findings"
                options={[
                  { value: "off", label: "Off" },
                  { value: "demote", label: "Balanced" },
                  { value: "drop", label: "Strict" },
                ]}
                value={verifyMode}
                onChange={onVerifyModeChange}
                hint={VERIFY_MODE_HINTS[verifyMode]}
                recommended={{ value: RECOMMENDED_VERIFY, label: "Balanced" }}
              />
            )}

            {onVerdictModeChange && (
              <OptionPicker
                title="Technique judging"
                options={[
                  { value: "menu", label: "Grouped" },
                  { value: "independent", label: "Individual" },
                ]}
                value={verdictMode}
                onChange={onVerdictModeChange}
                hint={VERDICT_MODE_HINTS[verdictMode]}
                recommended={{
                  value: recommendedVerdict,
                  label: recommendedVerdict === "menu" ? "Grouped" : "Individual",
                }}
              />
            )}

            {onOcrEnabledChange && (
              <>
                <OptionPicker
                  title="Read text in screenshots"
                  options={[
                    { value: "on", label: "On" },
                    { value: "off", label: "Off" },
                  ]}
                  value={ocrEnabled ? "on" : "off"}
                  onChange={(value) => onOcrEnabledChange(value === "on")}
                  hint={OCR_MODE_HINTS[ocrEnabled ? "on" : "off"]}
                />
                {ocrEnabled && (
                  <div className="badge badge-warning" style={{ width: "fit-content" }}>
                    ⚠ OCR finds more chunks to map, which means a bigger matrix and a longer run — roughly 15-30s more just for OCR itself, plus whatever mapping that extra evidence adds.
                  </div>
                )}
              </>
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
