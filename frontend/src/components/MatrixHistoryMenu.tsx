import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { deleteSavedMatrix, getMatrixHistory, type SavedMatrixSummary } from "../api/client";

/** Dropdown listing previously computed matrices (every finished mapping run,
 * persisted by the backend). Selecting one opens it in the full matrix editor
 * (/matrix?saved=<id>). Rendered on the upload hero, the dashboard header and
 * the matrix page header — the list is fetched fresh each time it opens. */
export default function MatrixHistoryMenu({ label = "Previous matrices" }: { label?: string }) {
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<SavedMatrixSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setError(null);
    getMatrixHistory()
      .then((list) => !cancelled && setEntries(list))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : String(err)));

    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      cancelled = true;
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function handleDelete(e: React.MouseEvent, id: string) {
    e.stopPropagation(); // don't also open the entry
    try {
      await deleteSavedMatrix(id);
      setEntries((list) => list?.filter((entry) => entry.id !== id) ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="matrix-menu" ref={ref}>
      <button
        className="btn"
        style={{ padding: "0.3rem 0.6rem", fontSize: "0.78rem" }}
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        {label} ▾
      </button>

      {open && (
        <div className="matrix-menu__dropdown matrix-history" role="menu">
          <div className="matrix-menu__label">Previously computed</div>
          {error && <div className="matrix-history__empty">{error}</div>}
          {!error && entries === null && <div className="matrix-history__empty">Loading…</div>}
          {!error && entries?.length === 0 && (
            <div className="matrix-history__empty">
              No matrices yet — they appear here after each report is mapped.
            </div>
          )}
          {entries?.map((entry) => (
            <button
              key={entry.id}
              className="matrix-menu__item matrix-history__item"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                navigate(`/matrix?saved=${entry.id}`);
              }}
              title={entry.filename ?? "Built by hand"}
            >
              <span className="matrix-history__name">{entry.name}</span>
              <span className="matrix-history__meta">
                {new Date(entry.updated_at ?? entry.created_at).toLocaleString()} · {entry.technique_count}{" "}
                techniques
              </span>
              <span
                className="matrix-history__delete"
                role="button"
                aria-label={`Delete ${entry.name}`}
                title="Delete this saved matrix"
                onClick={(e) => void handleDelete(e, entry.id)}
              >
                ×
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
