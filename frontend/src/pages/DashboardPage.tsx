import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  cancelIngest,
  cancelMapping,
  deleteSavedMatrix,
  getMatrixHistory,
  startMapping,
  type IngestStarted,
  type ReportType,
  type SavedMatrixSummary,
  type VerdictMode,
  type VerifyMode,
} from "../api/client";
import { BackIcon } from "../components/icons";
import MatrixHistoryMenu from "../components/MatrixHistoryMenu";
import MatrixOverview from "../components/MatrixOverview";
import MatrixWorkspace from "../components/MatrixWorkspace";
import ProgressBubble from "../components/ProgressBubble";
import ProgressPanel from "../components/ProgressPanel";
import UploadPanel from "../components/UploadPanel";
import { useAttackData } from "../hooks/useAttackData";
import { useIngestJob, useMappingJob } from "../hooks/useJobPolling";
import { layerToState } from "../types/attack";
import { clearActiveRun, loadActiveRun, saveActiveRun } from "../utils/activeRun";
import { readStored, writeStored } from "../utils/storage";
import { formatDuration } from "../utils/format";

/** The main dashboard is the matrix library: upload a new report, or open,
 * edit and delete previously computed matrices. While a report is being
 * processed it switches to the live run view (matrix preview filling in +
 * floating progress bubble), and back to the library afterwards. */
export default function DashboardPage() {
  // Rehydrate an in-flight run left behind by a tab close or reload: the
  // backend job survives keyed by report_id, so resuming just means re-adopting
  // the id and letting the polling hooks pick it back up. The first poll
  // overwrites this "parsing" placeholder. See utils/activeRun.
  const persistedRun = useMemo(() => loadActiveRun(), []);
  // The header logo navigates to "/" with `{ home: true }` so it can force the
  // library view even when the run view already lives at "/" (same route, so
  // the Link alone changes nothing). A plain reload/direct visit has no such
  // state and instead resumes the run view below.
  const location = useLocation();
  const cameHome = (location.state as { home?: boolean } | null)?.home === true;
  const [started, setStarted] = useState<IngestStarted | null>(
    persistedRun
      ? { report_id: persistedRun.reportId, filename: persistedRun.filename, status: "parsing" }
      : null,
  );
  // Verification mode (removes low-confidence findings): chosen before
  // upload, applied when the mapping run starts. Persisted so the choice
  // sticks. Balanced ("demote") is the recommended default — see
  // RECOMMENDED_VERIFY in UploadPanel.tsx.
  const [verifyMode, setVerifyMode] = useState<VerifyMode>(() => {
    const saved = readStored("tfm-verify-mode");
    return saved === "off" || saved === "drop" ? saved : "demote";
  });
  function handleVerifyModeChange(value: VerifyMode) {
    setVerifyMode(value);
    writeStored("tfm-verify-mode", value);
  }
  // Verdict architecture (grouped vs individual technique judging), same
  // ownership pattern as verifyMode.
  const [verdictMode, setVerdictMode] = useState<VerdictMode>(() =>
    readStored("tfm-verdict-mode") === "independent" ? "independent" : "menu",
  );
  function handleVerdictModeChange(value: VerdictMode) {
    setVerdictMode(value);
    writeStored("tfm-verdict-mode", value);
  }
  // Report kind (incident vs pentest), same ownership pattern — picked in the
  // upload dialog, applied when the mapping run starts. Persisting the last
  // choice also covers a resumed session's auto-started mapping.
  const [reportType, setReportType] = useState<ReportType>(() =>
    readStored("tfm-report-type") === "pentest" ? "pentest" : "incident",
  );
  function handleReportTypeChange(value: ReportType) {
    setReportType(value);
    writeStored("tfm-report-type", value);
  }
  // OCR for embedded screenshots (console output, dashboards, sandbox logs) —
  // same ownership pattern as the above. Defaults on; measured effect is
  // genre-dependent (clear recall win on log/terminal-heavy reports, noisier
  // on UI-screenshot-heavy ones), so unlike the others this has no
  // recommended value — see CLAUDE.md's DFIR OCR evaluation notes.
  const [ocrEnabled, setOcrEnabled] = useState<boolean>(
    () => readStored("tfm-ocr-enabled") !== "off",
  );
  function handleOcrEnabledChange(value: boolean) {
    setOcrEnabled(value);
    writeStored("tfm-ocr-enabled", value ? "on" : "off");
  }
  const [mappingReportId, setMappingReportId] = useState<string | null>(
    persistedRun?.mappingStarted ? persistedRun.reportId : null,
  );
  const [mapAttempt, setMapAttempt] = useState(0);
  const [runError, setRunError] = useState<string | null>(null);
  const [startingMap, setStartingMap] = useState(false);
  const [showDoneToast, setShowDoneToast] = useState(false);
  // Which screen is showing. Decoupled from `started` on purpose: going to the
  // library ("← All matrices") switches the view but keeps `started` /
  // `mappingReportId` alive, so the pipeline keeps polling in the background
  // and the run stays resumable via a banner — instead of being abandoned. A
  // rehydrated run opens straight into its run view.
  const [view, setView] = useState<"run" | "library">(
    cameHome ? "library" : persistedRun ? "run" : "library",
  );
  // Clicking the header logo (a fresh navigation to "/" carrying `home`) snaps
  // back to the library, keeping any in-progress run resumable in the banner.
  useEffect(() => {
    if (cameHome) setView("library");
  }, [location.key, cameHome]);
  // Library state.
  const [entries, setEntries] = useState<SavedMatrixSummary[] | null>(null);
  const [libraryError, setLibraryError] = useState<string | null>(null);

  // A restored run whose backend job no longer exists (the status endpoint
  // 404s — e.g. the backend restarted since the tab was closed) is stale:
  // forget it and fall back to the library, where any completed run still is.
  const dropStaleRun = useCallback(() => {
    setStarted(null);
    setMappingReportId(null);
    setShowDoneToast(false);
    setView("library");
    clearActiveRun();
  }, []);

  const job = useIngestJob(started?.report_id ?? null, dropStaleRun);
  const mappingJob = useMappingJob(mappingReportId, mapAttempt, dropStaleRun);
  const { catalog, loading, error } = useAttackData();

  // A new upload replaces the previous report *and* its mapping run.
  function handleStarted(next: IngestStarted) {
    setMappingReportId(null);
    setShowDoneToast(false);
    setStarted(next);
    setView("run");
    // Remember it so a reload during processing returns to this run.
    saveActiveRun({ reportId: next.report_id, filename: next.filename, mappingStarted: false });
  }

  async function handleGenerate() {
    if (!started) return;
    setStartingMap(true);
    setRunError(null);
    try {
      await startMapping(started.report_id, {
        verify_mode: verifyMode,
        verdict_mode: verdictMode,
        report_type: reportType,
      });
      setMappingReportId(started.report_id);
      // Record that mapping is underway, so a reload resumes the map job
      // directly instead of re-triggering the auto-start.
      saveActiveRun({ reportId: started.report_id, filename: started.filename, mappingStarted: true });
      setMapAttempt((a) => a + 1); // restart polling even if the report id didn't change (retry)
    } catch (e) {
      // Failures once the job is running are reported by the status endpoint;
      // this only covers not being able to start it.
      setRunError(e instanceof Error ? e.message : String(e));
    } finally {
      setStartingMap(false);
    }
  }

  // Mapping starts itself the moment ingestion finishes — no button. Guarded
  // so a poll tick can't double-start the same report's run.
  const ingestDone = job?.status === "done" && job.report_id === started?.report_id;
  useEffect(() => {
    if (ingestDone && !startingMap && mappingReportId !== started!.report_id) {
      void handleGenerate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ingestDone, mappingReportId]);

  // Pop the "matrix ready" toast when the mapping run reaches "done", and stop
  // persisting the run: it's finished and now lives in the library, so a reload
  // should land there rather than re-open this (in-memory) finished editor.
  const mappingDone = mappingJob?.status === "done";
  useEffect(() => {
    if (mappingDone) {
      setShowDoneToast(true);
      clearActiveRun();
    }
  }, [mappingDone]);

  // Stop the run and free the user: request cancellation of whichever stage
  // is active, then return to the library right away — the backend settles
  // the job to "cancelled" at its next safe boundary on its own.
  const [cancelling, setCancelling] = useState(false);
  async function handleCancelRun() {
    if (!started) return;
    setCancelling(true);
    try {
      if (mappingReportId) {
        await cancelMapping(mappingReportId);
      } else {
        await cancelIngest(started.report_id);
      }
    } catch {
      // Job may have finished in the meantime — leaving is still correct.
    } finally {
      setCancelling(false);
      setStarted(null);
      setMappingReportId(null);
      setShowDoneToast(false);
      setView("library");
      clearActiveRun();
    }
  }

  // If the backend reports the job cancelled from elsewhere, leave the run
  // view too — there's nothing left to watch.
  const runCancelled = job?.status === "cancelled" || mappingJob?.status === "cancelled";
  useEffect(() => {
    if (runCancelled) {
      setStarted(null);
      setMappingReportId(null);
      setView("library");
      clearActiveRun();
    }
  }, [runCancelled]);

  // (Re)load the library whenever it's the visible view, and again the moment a
  // background run completes (so its freshly-saved entry appears without having
  // to leave and come back).
  useEffect(() => {
    if (view !== "library") return;
    let cancelled = false;
    setLibraryError(null);
    getMatrixHistory()
      .then((list) => !cancelled && setEntries(list))
      .catch((err) => !cancelled && setLibraryError(err instanceof Error ? err.message : String(err)));
    return () => {
      cancelled = true;
    };
  }, [view, mappingDone]);

  async function handleDelete(e: React.MouseEvent, id: string) {
    e.preventDefault(); // the card is a link now — don't navigate
    e.stopPropagation();
    try {
      await deleteSavedMatrix(id);
      setEntries((list) => list?.filter((entry) => entry.id !== id) ?? null);
    } catch (err) {
      setLibraryError(err instanceof Error ? err.message : String(err));
    }
  }

  // Bring the (still-polling) run view back to the foreground.
  function resumeRun() {
    setView("run");
  }

  // A short live status line for the resume banner.
  function runStatusLabel(): string {
    if (mappingJob) {
      switch (mappingJob.status) {
        case "mapping":
          return `Mapping techniques… ${mappingJob.chunks_mapped}/${mappingJob.chunk_count}`;
        case "warming":
          return "Loading the model…";
        case "retrieving":
          return "Retrieving candidates…";
        case "aggregating":
          return "Finishing up…";
        case "error":
          return "Mapping failed — reopen to retry";
        default:
          return "Mapping…";
      }
    }
    if (job) {
      switch (job.status) {
        case "embedding":
          return `Embedding chunks… ${job.chunks_embedded}/${job.chunk_count}`;
        case "parsing":
          return "Extracting text…";
        case "chunking":
          return "Chunking sections…";
        case "error":
          return "Ingest failed — reopen to retry";
        default:
          return "Processing…";
      }
    }
    return "Processing…";
  }

  // The library view — upload a new report, resume an in-progress run, or open a
  // saved matrix. Shown whenever the library is selected; an active run (if any)
  // keeps polling in the background and is offered as a resume banner, while a
  // finished run appears as a card in the grid.
  if (view === "library" || !started) {
    const showResume = started !== null && !mappingDone;
    return (
      <div className="dashboard-main">
        <section className="dashboard-main__upload">
          <h1 className="dashboard-hero__title">Upload a security report</h1>
          <p className="dashboard-hero__subtitle">
            Drop an incident report, pentest result, or security policy PDF to generate its ATT&amp;CK matrix.
          </p>
          <UploadPanel
            onStarted={handleStarted}
            verifyMode={verifyMode}
            onVerifyModeChange={handleVerifyModeChange}
            verdictMode={verdictMode}
            onVerdictModeChange={handleVerdictModeChange}
            reportType={reportType}
            onReportTypeChange={handleReportTypeChange}
            ocrEnabled={ocrEnabled}
            onOcrEnabledChange={handleOcrEnabledChange}
          />
        </section>

        {showResume && (
          <button type="button" className="run-resume" onClick={resumeRun}>
            <span className="run-resume__dot" aria-hidden />
            <span className="run-resume__text">
              <span className="run-resume__label">Report in progress</span>
              <span className="run-resume__detail">
                <span className="run-resume__file">{started!.filename}</span>
                <span className="run-resume__status">{runStatusLabel()}</span>
              </span>
            </span>
            <span className="run-resume__cta">Resume</span>
          </button>
        )}

        <section className="matrix-library">
          <div className="matrix-library__header">
            <h2>Your matrices</h2>
            {entries && entries.length > 0 && (
              <span className="matrix-library__count">{entries.length}</span>
            )}
            <Link to="/matrix" className="btn matrix-library__editor-link">
              Open editor ↗
            </Link>
          </div>

          {libraryError && <p className="matrix-library__empty">{libraryError}</p>}
          {!libraryError && entries === null && <p className="matrix-library__empty">Loading…</p>}
          {!libraryError && entries?.length === 0 && (
            <p className="matrix-library__empty">
              No matrices yet — upload a report above to generate your first one, or build one by hand in
              the editor and save it.
            </p>
          )}

          {entries && entries.length > 0 && (
            <div className="matrix-library__grid">
              {entries.map((entry) => (
                // A real link (not a div with onClick) so middle-click / ctrl-click
                // opens the matrix in a new tab; plain click still SPA-navigates.
                <Link
                  key={entry.id}
                  to={`/matrix?saved=${entry.id}`}
                  className="matrix-card"
                  title="Open in the matrix editor"
                >
                  <div className="matrix-card__top">
                    <span className="matrix-card__name">{entry.name}</span>
                    <button
                      className="matrix-card__delete"
                      aria-label={`Delete ${entry.name}`}
                      title="Delete this matrix"
                      onClick={(e) => void handleDelete(e, entry.id)}
                    >
                      ×
                    </button>
                  </div>
                  <span className="matrix-card__meta">
                    {entry.filename ? `From ${entry.filename}` : "Built by hand"}
                    {entry.duration_seconds != null && ` · mapped in ${formatDuration(entry.duration_seconds)}`}
                  </span>
                  <div className="matrix-card__footer">
                    <span className="badge">{entry.technique_count} techniques</span>
                    <span className="matrix-card__date">
                      {new Date(entry.updated_at ?? entry.created_at).toLocaleString()}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </section>
      </div>
    );
  }

  // The matrix only ever shows the current report's mapping run: empty while
  // a (re-)upload is ingesting — a new upload resets `mappingReportId`, so old
  // mappings never linger — then filling in live as chunks are mapped (the
  // layer is rebuilt after every chunk).
  const displayedState = mappingJob?.layer ? layerToState(mappingJob.layer) : {};

  // While the pipeline is still updating the matrix (anything before a
  // terminal mapping state), the preview pulses so it reads as "in progress".
  const computing =
    (job !== null && job.status !== "done" && job.status !== "error") ||
    (mappingJob !== null && mappingJob.status !== "done" && mappingJob.status !== "error") ||
    (job?.status === "done" && mappingJob === null); // mapping about to auto-start

  // Run finished: the progress bubble goes away and the run view becomes the
  // full editor, in place — review the mappings, correct them, Save (the run
  // is already in the library; Save updates that same entry via its
  // tfm_saved_id stamp).
  const finished = mappingDone && Boolean(mappingJob?.layer);

  // "← All matrices": show the library but keep the run alive and resumable in
  // the background (it re-appears as the resume banner). If it already
  // finished there's nothing left to resume — it's a library entry now — so
  // fully reset instead.
  function backToLibrary() {
    setShowDoneToast(false);
    setView("library");
    if (mappingDone) {
      setStarted(null);
      setMappingReportId(null);
      clearActiveRun();
    }
  }

  // Active run: the matrix fills the page and progress lives in a draggable
  // floating bubble on top of it, so the user watches the pipeline move rather
  // than a spinner. Scored cells stay clickable throughout — a read-only
  // popover shows each technique's evidence as it lands.
  return (
    <div className="dashboard-loaded">
      {runError && (
        <div className="matrix-import-error">
          {runError}
          <button onClick={() => setRunError(null)} aria-label="Dismiss">
            ×
          </button>
        </div>
      )}
      {finished && catalog ? (
        <MatrixWorkspace
          catalog={catalog}
          layer={mappingJob!.layer}
          leading={
            <button className="btn btn-sm btn-back" onClick={backToLibrary}>
              <BackIcon />
              All matrices
            </button>
          }
        />
      ) : (
        <section className="dashboard-loaded__matrix">
          <div className="panel-header" style={{ justifyContent: "space-between" }}>
            <h2>ATT&amp;CK Matrix</h2>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button className="btn btn-sm btn-back" onClick={backToLibrary}>
                <BackIcon />
                All matrices
              </button>
              <MatrixHistoryMenu label="History" />
            </div>
          </div>
          <div className="dashboard-loaded__matrix-body">
            {loading && (
              <div className="empty-state">
                <h3>Loading matrix…</h3>
              </div>
            )}
            {error && (
              <div className="empty-state">
                <h3>Couldn&apos;t load the matrix</h3>
                <p>{error}</p>
              </div>
            )}
            {catalog && <MatrixOverview catalog={catalog} layer={displayedState} computing={computing} />}
          </div>
        </section>
      )}

      {!finished && (
        <ProgressBubble title="Progress" subtitle={started.filename}>
          <ProgressPanel
            job={job}
            mappingJob={mappingJob}
            onGenerate={handleGenerate}
            generateDisabled={startingMap}
            onCancel={() => void handleCancelRun()}
            cancelDisabled={cancelling}
          />
        </ProgressBubble>
      )}

      {showDoneToast && (
        <div className="matrix-toast" role="status">
          <span className="matrix-toast__icon">✓</span>
          <div className="matrix-toast__body">
            <strong>Matrix generated{mappingJob ? ` in ${formatDuration(mappingJob.elapsed_seconds)}` : ""}</strong>
            <span>
              {mappingJob?.layer ? `${mappingJob.layer.techniques.length} techniques identified in ` : ""}
              {started.filename} — saved to your library. Review and edit it below.
            </span>
          </div>
          <button
            className="matrix-toast__dismiss"
            onClick={() => setShowDoneToast(false)}
            aria-label="Dismiss notification"
          >
            ×
          </button>
        </div>
      )}
    </div>
  );
}
