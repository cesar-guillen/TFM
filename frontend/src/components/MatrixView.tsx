export default function MatrixView() {
  return (
    <>
      <div className="panel-header">
        <h2>ATT&amp;CK Matrix</h2>
      </div>
      <div className="panel-body">
        <div className="empty-state">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none">
            <rect x="1.5" y="1.5" width="6" height="6" rx="1.2" stroke="currentColor" strokeWidth="1.4" />
            <rect x="9" y="1.5" width="6" height="6" rx="1.2" stroke="currentColor" strokeWidth="1.4" />
            <rect x="16.5" y="1.5" width="6" height="6" rx="1.2" stroke="currentColor" strokeWidth="1.4" />
            <rect x="1.5" y="9" width="6" height="6" rx="1.2" stroke="currentColor" strokeWidth="1.4" />
            <rect x="9" y="9" width="6" height="6" rx="1.2" stroke="currentColor" strokeWidth="1.4" />
            <rect x="16.5" y="9" width="6" height="6" rx="1.2" stroke="currentColor" strokeWidth="1.4" />
            <rect x="1.5" y="16.5" width="6" height="6" rx="1.2" stroke="currentColor" strokeWidth="1.4" />
            <rect x="9" y="16.5" width="6" height="6" rx="1.2" stroke="currentColor" strokeWidth="1.4" />
            <rect x="16.5" y="16.5" width="6" height="6" rx="1.2" stroke="currentColor" strokeWidth="1.4" />
          </svg>
          <h3>No matrix yet</h3>
          <p>
            Upload a report to extract evidence, then the RAG pipeline will map it to
            MITRE ATT&amp;CK techniques here. This view is a placeholder — the mapping
            pipeline hasn't landed yet.
          </p>
        </div>
      </div>
    </>
  );
}
