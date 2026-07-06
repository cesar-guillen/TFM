import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { startMapping, type IngestStarted } from "../api/client";
import MatrixOverview from "../components/MatrixOverview";
import ProgressPanel from "../components/ProgressPanel";
import ReportPanel from "../components/ReportPanel";
import UploadPanel from "../components/UploadPanel";
import { useAttackData } from "../hooks/useAttackData";
import { useIngestJob } from "../hooks/useIngestJob";
import { useMappingJob } from "../hooks/useMappingJob";
import { layerToState } from "../types/attack";

export default function DashboardPage() {
  const [started, setStarted] = useState<IngestStarted | null>(null);
  const [mappingReportId, setMappingReportId] = useState<string | null>(null);
  const [mapAttempt, setMapAttempt] = useState(0);
  const [startingMap, setStartingMap] = useState(false);
  const job = useIngestJob(started?.report_id ?? null);
  const mappingJob = useMappingJob(mappingReportId, mapAttempt);
  const { catalog, loading, error } = useAttackData();

  // A new upload replaces the previous report *and* its mapping run.
  function handleStarted(next: IngestStarted) {
    setMappingReportId(null);
    setStarted(next);
  }

  async function handleGenerate() {
    if (!started) return;
    setStartingMap(true);
    try {
      await startMapping(started.report_id);
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

  // Before the first report is uploaded: just the upload window, centered.
  if (!started) {
    return (
      <div className="dashboard-hero">
        <div className="dashboard-hero__card">
          <h1 className="dashboard-hero__title">Upload a security report</h1>
          <p className="dashboard-hero__subtitle">
            Drop an incident report, pentest result, or security policy PDF to generate its ATT&amp;CK matrix.
          </p>
          <UploadPanel variant="hero" onStarted={handleStarted} />
        </div>
      </div>
    );
  }

  // The matrix only ever shows the current report's mapping run: empty while
  // a (re-)upload is ingesting — a new upload resets `mappingReportId`, so old
  // mappings never linger — then filling in live as chunks are mapped (the
  // layer is rebuilt after every chunk).
  const displayedState = mappingJob?.layer ? layerToState(mappingJob.layer) : {};

  // As soon as an upload starts (not once it finishes): matrix (top ~70%) +
  // ingest progress & report (~30%), so the user sees the pipeline actually
  // moving instead of staring at a spinner for the ~100s+ embedding takes.
  return (
    <div className="dashboard-loaded">
      <section className="dashboard-loaded__matrix">
        <div className="panel-header" style={{ justifyContent: "space-between" }}>
          <h2>ATT&amp;CK Matrix</h2>
          <Link to="/matrix" className="btn" style={{ padding: "0.3rem 0.6rem", fontSize: "0.78rem" }}>
            Open full matrix ↗
          </Link>
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
          {catalog && <MatrixOverview catalog={catalog} layer={displayedState} />}
        </div>
      </section>

      <section className="dashboard-loaded__bottom">
        <div className="dashboard-loaded__progress">
          <ProgressPanel
            job={job}
            mappingJob={mappingJob}
            onGenerate={handleGenerate}
            generateDisabled={startingMap}
          />
        </div>
        <div className="dashboard-loaded__report">
          <ReportPanel filename={started.filename} job={job} onStarted={handleStarted} />
        </div>
      </section>
    </div>
  );
}
