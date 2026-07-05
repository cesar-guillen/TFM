import { useState } from "react";
import { Link } from "react-router-dom";
import type { IngestStarted } from "../api/client";
import MatrixOverview from "../components/MatrixOverview";
import ProgressPanel from "../components/ProgressPanel";
import ReportPanel from "../components/ReportPanel";
import UploadPanel from "../components/UploadPanel";
import { useAttackData } from "../hooks/useAttackData";
import { useIngestJob } from "../hooks/useIngestJob";
import { layerToState } from "../types/attack";

export default function DashboardPage() {
  const [started, setStarted] = useState<IngestStarted | null>(null);
  const job = useIngestJob(started?.report_id ?? null);
  const { catalog, layer, loading, error } = useAttackData();

  // Before the first report is uploaded: just the upload window, centered.
  if (!started) {
    return (
      <div className="dashboard-hero">
        <div className="dashboard-hero__card">
          <h1 className="dashboard-hero__title">Upload a security report</h1>
          <p className="dashboard-hero__subtitle">
            Drop an incident report, pentest result, or security policy PDF to generate its ATT&amp;CK matrix.
          </p>
          <UploadPanel variant="hero" onStarted={setStarted} />
        </div>
      </div>
    );
  }

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
          {catalog && layer && <MatrixOverview catalog={catalog} layer={layerToState(layer)} />}
        </div>
      </section>

      <section className="dashboard-loaded__bottom">
        <div className="dashboard-loaded__progress">
          <ProgressPanel job={job} />
        </div>
        <div className="dashboard-loaded__report">
          <ReportPanel filename={started.filename} job={job} onStarted={setStarted} />
        </div>
      </section>
    </div>
  );
}
