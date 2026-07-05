import { useState } from "react";
import { Link } from "react-router-dom";
import ChatPanel from "../components/ChatPanel";
import MatrixOverview from "../components/MatrixOverview";
import ReportPanel from "../components/ReportPanel";
import UploadPanel, { type IngestResult } from "../components/UploadPanel";
import { useAttackData } from "../hooks/useAttackData";
import { layerToState } from "../types/attack";

export default function DashboardPage() {
  const [report, setReport] = useState<IngestResult | null>(null);
  const { catalog, layer, loading, error } = useAttackData();

  // Before the first report is uploaded: just the upload window, centered.
  if (!report) {
    return (
      <div className="dashboard-hero">
        <div className="dashboard-hero__card">
          <h1 className="dashboard-hero__title">Upload a security report</h1>
          <p className="dashboard-hero__subtitle">
            Drop an incident report, pentest result, or security policy PDF to generate its ATT&amp;CK matrix.
          </p>
          <UploadPanel variant="hero" onUploaded={setReport} />
        </div>
      </div>
    );
  }

  // After upload: matrix (top ~70%, scaled to fit) + chat & report (~30%).
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
        <div className="dashboard-loaded__chat">
          <ChatPanel />
        </div>
        <div className="dashboard-loaded__report">
          <ReportPanel report={report} onUploaded={setReport} />
        </div>
      </section>
    </div>
  );
}
