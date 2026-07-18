import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  cancelIngest,
  cancelMapping,
  deleteSavedMatrix,
  getMatrixHistory,
  startMapping,
  type IngestStarted,
  type SavedMatrixSummary,
  type VerifyMode,
} from "../api/client";
import MatrixHistoryMenu from "../components/MatrixHistoryMenu";
import MatrixOverview from "../components/MatrixOverview";
import MatrixWorkspace from "../components/MatrixWorkspace";
import ProgressBubble from "../components/ProgressBubble";
import ProgressPanel from "../components/ProgressPanel";
import UploadPanel from "../components/UploadPanel";
import { useAttackData } from "../hooks/useAttackData";
import { useIngestJob } from "../hooks/useIngestJob";
import { useMappingJob } from "../hooks/useMappingJob";
import { layerToState } from "../types/attack";
import { formatDuration } from "../utils/format";

/** The main dashboard is the matrix library: upload a new report, or open,
 * edit and delete previously computed matrices. While a report is being
 * processed it switches to the live run view (matrix preview filling in +
 * floating progress bubble), and back to the library afterwards. */
export default function DashboardPage() {
  const [started, setStarted] = useState<IngestStarted | null>(null);
  // Verification mode (false-positive filtering): chosen before upload,
  // applied when the mapping run starts. Persisted so the choice sticks.
  const [verifyMode, setVerifyMode] = useState<VerifyMode>(() => {
    const saved = localStorage.getItem("tfm-verify-mode");
    return saved === "demote" || saved === "drop" ? saved : "off";
  });
  function handleVerifyModeChange(value: VerifyMode) {
    setVerifyMode(value);
    localStorage.setItem("tfm-verify-mode", value);
  }
  const [mappingReportId, setMappingReportId] = useState<string | null>(null);
  const [mapAttempt, setMapAttempt] = useState(0);
  const [startingMap, setStartingMap] = useState(false);
  const [showDoneToast, setShowDoneToast] = useState(false);
  // Library state (only shown/fetched while no run is active).
  const [entries, setEntries] = useState<SavedMatrixSummary[] | null>(null);
  const [libraryError, setLibraryError] = useState<string | null>(null);
  const job = useIngestJob(started?.report_id ?? null);
  const mappingJob = useMappingJob(mappingReportId, mapAttempt);
  const { catalog, loading, error } = useAttackData();
  const navigate = useNavigate();

  // A new upload replaces the previous report *and* its mapping run.
  function handleStarted(next: IngestStarted) {
    setMappingReportId(null);
    setShowDoneToast(false);
    setStarted(next);
  }

  async function handleGenerate() {
    if (!started) return;
    setStartingMap(true);
    try {
      await startMapping(started.report_id, { verify_mode: verifyMode });
      setMappingReportId(started.report_id);
      setMapAttempt((a) => a + 1); // restart polling even if the report id didn't change (retry)
    } catch (e) {
      // Surfaced crudely for now; the status endpoint reports job-level errors.
      alert(e instanceof Error ? e.message : String(e));
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

  // Pop the "matrix ready" toast when the mapping run reaches "done".
  const mappingDone = mappingJob?.status === "done";
  useEffect(() => {
    if (mappingDone) setShowDoneToast(true);
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
    }
  }

  // If the backend reports the job cancelled from elsewhere, leave the run
  // view too — there's nothing left to watch.
  const runCancelled = job?.status === "cancelled" || mappingJob?.status === "cancelled";
  useEffect(() => {
    if (runCancelled) {
      setStarted(null);
      setMappingReportId(null);
    }
  }, [runCancelled]);

  // (Re)load the library whenever it's the visible view — including on return
  // from a run, which will have added its own entry.
  useEffect(() => {
    if (started) return;
    let cancelled = false;
    setLibraryError(null);
    getMatrixHistory()
      .then((list) => !cancelled && setEntries(list))
      .catch((err) => !cancelled && setLibraryError(err instanceof Error ? err.message : String(err)));
    return () => {
      cancelled = true;
    };
  }, [started]);

  async function handleDelete(e: React.MouseEvent, id: string) {
    e.stopPropagation(); // don't also open the card
    try {
      await deleteSavedMatrix(id);
      setEntries((list) => list?.filter((entry) => entry.id !== id) ?? null);
    } catch (err) {
      setLibraryError(err instanceof Error ? err.message : String(err));
    }
  }

  // No active run: the library — upload a new report, or open a saved matrix.
  if (!started) {
    return (
      <div className="dashboard-main">
        <section className="dashboard-main__upload">
          <h1 className="dashboard-hero__title">Upload a security report</h1>
          <p className="dashboard-hero__subtitle">
            Drop an incident report, pentest result, or security policy PDF to generate its ATT&amp;CK matrix.
          </p>
          <UploadPanel
            variant="hero"
            onStarted={handleStarted}
            verifyMode={verifyMode}
            onVerifyModeChange={handleVerifyModeChange}
          />
        </section>

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
                <div
                  key={entry.id}
                  className="matrix-card"
                  role="button"
                  tabIndex={0}
                  onClick={() => navigate(`/matrix?saved=${entry.id}`)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") navigate(`/matrix?saved=${entry.id}`);
                  }}
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
                </div>
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

  function backToLibrary() {
    setStarted(null);
    setMappingReportId(null);
    setShowDoneToast(false);
  }

  // Active run: the matrix fills the page and progress lives in a draggable
  // floating bubble on top of it, so the user sees the pipeline actually
  // moving instead of staring at a spinner for the ~100s+ embedding takes.
  // Scored cells are clickable throughout the run — a read-only popover shows
  // the technique's evidence as it lands. "All matrices" goes back to the
  // library (which refetches, so the run that just finished is in it).
  return (
    <div className="dashboard-loaded">
      {finished && catalog ? (
        <MatrixWorkspace
          catalog={catalog}
          layer={mappingJob!.layer}
          leading={
            <button className="btn" style={{ padding: "0.3rem 0.6rem", fontSize: "0.78rem" }} onClick={backToLibrary}>
              ← All matrices
            </button>
          }
        />
      ) : (
        <section className="dashboard-loaded__matrix">
          <div className="panel-header" style={{ justifyContent: "space-between" }}>
            <h2>ATT&amp;CK Matrix</h2>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button
                className="btn"
                style={{ padding: "0.3rem 0.6rem", fontSize: "0.78rem" }}
                onClick={backToLibrary}
              >
                ← All matrices
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
