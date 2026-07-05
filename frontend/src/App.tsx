import { Route, Routes } from "react-router-dom";
import DashboardPage from "./pages/DashboardPage";
import MatrixPage from "./pages/MatrixPage";

export default function App() {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.6rem",
          height: "56px",
          minHeight: "56px",
          padding: "0 1.25rem",
          borderBottom: "1px solid var(--border)",
          background: "var(--bg-raised)",
        }}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
          <rect x="2" y="2" width="8.5" height="8.5" rx="2" fill="#7c8cff" />
          <rect x="13.5" y="2" width="8.5" height="8.5" rx="2" fill="#7c8cff" opacity="0.55" />
          <rect x="2" y="13.5" width="8.5" height="8.5" rx="2" fill="#7c8cff" opacity="0.55" />
          <rect x="13.5" y="13.5" width="8.5" height="8.5" rx="2" fill="#7c8cff" opacity="0.3" />
        </svg>
        <span style={{ fontWeight: 600, fontSize: "0.95rem", letterSpacing: "-0.01em" }}>
          ATT&amp;CK Mapper
        </span>
        <span style={{ color: "var(--text-faint)", fontSize: "0.8rem", marginLeft: "0.25rem" }}>
          local, RAG-grounded TTP extraction
        </span>
      </header>

      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/matrix" element={<MatrixPage />} />
      </Routes>
    </div>
  );
}
