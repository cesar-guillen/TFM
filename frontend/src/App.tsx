import { Link, Route, Routes } from "react-router-dom";
import DashboardPage from "./pages/DashboardPage";
import MatrixPage from "./pages/MatrixPage";

export default function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <Link to="/" state={{ home: true }} title="Back to the dashboard" className="app-header__brand">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <rect x="2" y="2" width="8.5" height="8.5" rx="2" fill="#7c8cff" />
            <rect x="13.5" y="2" width="8.5" height="8.5" rx="2" fill="#7c8cff" opacity="0.55" />
            <rect x="2" y="13.5" width="8.5" height="8.5" rx="2" fill="#7c8cff" opacity="0.55" />
            <rect x="13.5" y="13.5" width="8.5" height="8.5" rx="2" fill="#7c8cff" opacity="0.3" />
          </svg>
          <span className="app-header__name">ATT&amp;CK Mapper</span>
        </Link>
        <span className="app-header__tagline">local, RAG-grounded TTP extraction</span>
      </header>

      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/matrix" element={<MatrixPage />} />
      </Routes>
    </div>
  );
}
