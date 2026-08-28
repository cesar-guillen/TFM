import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getSavedMatrix } from "../api/client";
import { BackIcon } from "../components/icons";
import MatrixWorkspace from "../components/MatrixWorkspace";
import { useAttackData } from "../hooks/useAttackData";
import type { Layer } from "../types/attack";

/** The standalone matrix editor route: bare (reached via the library's "Open
 * editor ↗") starts a blank hand-built matrix; with ?saved=<id> (dashboard
 * cards / history menu) it loads that library entry instead. Hands whichever
 * one applies to the shared MatrixWorkspace editor. */
export default function MatrixPage() {
  const { catalog, loading, error } = useAttackData();
  const [savedLayer, setSavedLayer] = useState<Layer | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  // True after an import: the grid belongs to the imported file, so neither
  // the current layer nor a stale ?saved fetch may overwrite it.
  const [detached, setDetached] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const savedId = searchParams.get("saved");

  useEffect(() => {
    if (!savedId) {
      setSavedLayer(null);
      return;
    }
    let cancelled = false;
    getSavedMatrix(savedId)
      .then((saved) => {
        if (cancelled) return;
        // Navigating to a saved entry always takes over the grid.
        setDetached(false);
        setSavedLayer({ ...saved.layer, name: saved.layer.name || saved.name });
      })
      .catch((err) => {
        if (!cancelled) setPageError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [savedId]);

  // What the workspace grid follows: a saved entry's layer once loaded, or
  // null (blank matrix, ready for hand-building) while detached (import), not
  // viewing a saved entry, or still loading it.
  const shownLayer = detached || !savedId ? null : savedLayer;

  if (loading || error || !catalog) {
    return (
      <div className="empty-state">
        <h3>{error ? "Couldn't load the matrix" : "Loading matrix…"}</h3>
        {error && <p>{error}</p>}
      </div>
    );
  }

  return (
    <>
      {pageError && (
        <div className="matrix-import-error">
          {pageError}
          <button onClick={() => setPageError(null)} aria-label="Dismiss">
            ×
          </button>
        </div>
      )}
      <MatrixWorkspace
        catalog={catalog}
        layer={shownLayer}
        saveTargetId={savedId}
        leading={
          <Link to="/" className="btn btn-sm btn-back">
            <BackIcon />
            Dashboard
          </Link>
        }
        onImported={() => {
          setDetached(true);
          if (savedId) setSearchParams({}, { replace: true });
        }}
        onSavedEntry={(id) => {
          setDetached(false);
          if (savedId !== id) setSearchParams({ saved: id }, { replace: true });
        }}
      />
    </>
  );
}
