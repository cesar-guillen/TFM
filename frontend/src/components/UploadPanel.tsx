import { useRef, useState } from "react";
import { ingestPdf } from "../api/client";

export default function UploadPanel() {
  const [markdown, setMarkdown] = useState<string>("");
  const [filename, setFilename] = useState<string>("");
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
      setFilename(result.filename);
      setMarkdown(result.markdown);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <div className="panel-header">
        <h2>Source Report</h2>
      </div>
      <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        <div
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
          style={{
            border: `1.5px dashed ${dragOver ? "var(--accent)" : "var(--border)"}`,
            borderRadius: "var(--radius)",
            background: dragOver ? "var(--accent-soft)" : "var(--bg-raised)",
            padding: "1.75rem 1rem",
            textAlign: "center",
            cursor: "pointer",
            transition: "border-color 0.15s ease, background 0.15s ease",
          }}
        >
          <svg
            width="28"
            height="28"
            viewBox="0 0 24 24"
            fill="none"
            style={{ margin: "0 auto 0.6rem", display: "block" }}
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
          <div style={{ fontSize: "0.85rem", fontWeight: 500 }}>
            Drop a PDF here, or click to browse
          </div>
          <div style={{ fontSize: "0.75rem", color: "var(--text-faint)", marginTop: "0.25rem" }}>
            Incident reports, pentest results, security policies
          </div>
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf"
            onChange={(e) => handleFiles(e.target.files)}
            style={{ display: "none" }}
          />
        </div>

        {loading && (
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.85rem", color: "var(--text-dim)" }}>
            <span className="badge">Parsing</span>
            Extracting text from PDF...
          </div>
        )}

        {error && (
          <div className="badge badge-danger" style={{ width: "fit-content" }}>
            {error}
          </div>
        )}

        {markdown && !loading && (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", minHeight: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <span className="badge">Parsed</span>
              <span style={{ fontSize: "0.8rem", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>
                {filename}
              </span>
            </div>
            <pre
              style={{
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                background: "var(--bg-raised)",
                border: "1px solid var(--border-soft)",
                borderRadius: "var(--radius)",
                padding: "0.85rem",
                fontSize: "0.78rem",
                lineHeight: 1.55,
                fontFamily: "var(--font-mono)",
                color: "var(--text-dim)",
                maxHeight: "50vh",
                overflow: "auto",
                margin: 0,
              }}
            >
              {markdown}
            </pre>
          </div>
        )}
      </div>
    </>
  );
}
