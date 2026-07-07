import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { createSavedMatrix, getSavedMatrix, updateSavedMatrix } from "../api/client";
import AttackMatrix from "../components/AttackMatrix";
import MatrixHistoryMenu from "../components/MatrixHistoryMenu";
import MatrixMenu from "../components/MatrixMenu";
import { useAttackData } from "../hooks/useAttackData";
import { useHeatTheme } from "../theme/heatThemes";
import {
  layerToState,
  stateToLayer,
  type Layer,
  type LayerState,
  type TechniqueSort,
} from "../types/attack";
import { buildMatrixSvg } from "../utils/matrixSvg";

function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function downloadJson(filename: string, data: unknown) {
  downloadBlob(filename, new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
}

/** Fallback layer metadata for matrices built from scratch (nothing generated
 * or opened yet) — mirrors the backend's empty_layer(). */
const DEFAULT_BASE: Layer = {
  name: "ATT&CK matrix",
  versions: { attack: "19", navigator: "5.1.0", layer: "4.5" },
  domain: "enterprise-attack",
  description: "",
  techniques: [],
};

/** What the grid was loaded from — guards the effects below against
 * clobbering each other (e.g. the current-layer load must not overwrite an
 * import after the ?saved param is cleared). */
type LayerSource = "current" | "saved" | "imported";

export default function MatrixPage() {
  const { catalog, layer, loading, error } = useAttackData();
  const { theme } = useHeatTheme();
  const [state, setState] = useState<LayerState>({});
  const [title, setTitle] = useState("ATT&CK matrix");
  const [sortBy, setSortBy] = useState<TechniqueSort>("default");
  const [pageError, setPageError] = useState<string | null>(null);
  // Metadata (versions/domain/tfm_saved_id) of whatever the grid was loaded
  // from — the base every export and save is built on.
  const [baseLayer, setBaseLayer] = useState<Layer | null>(null);
  const [source, setSource] = useState<LayerSource | null>(null);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved">("idle");
  // ?saved=<id> opens a matrix from the on-disk library (dashboard cards /
  // history menu) instead of the current in-memory layer.
  const [searchParams, setSearchParams] = useSearchParams();
  const savedId = searchParams.get("saved");

  // Initial load of the current generated layer — only while nothing else
  // (saved entry, import) has been loaded into the grid.
  useEffect(() => {
    if (layer && !savedId && source === null) {
      setBaseLayer(layer);
      setState(layerToState(layer));
      setTitle(layer.name);
      setSource("current");
    }
  }, [layer, savedId, source]);

  useEffect(() => {
    if (!savedId) return;
    let cancelled = false;
    getSavedMatrix(savedId)
      .then((saved) => {
        if (cancelled) return;
        setBaseLayer(saved.layer);
        setState(layerToState(saved.layer));
        setTitle(saved.layer.name || saved.name);
        setSource("saved");
      })
      .catch((err) => {
        if (!cancelled) setPageError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [savedId]);

  const exportBasename = (title.trim() || "attack_matrix").replace(/\s+/g, "_");

  function exportBase(): Layer {
    return { ...(baseLayer ?? DEFAULT_BASE), name: title.trim() || "ATT&CK matrix" };
  }

  function handleExportSvg() {
    if (!catalog) return;
    const svg = buildMatrixSvg({ catalog, state, theme, title: title.trim() || "ATT&CK matrix", sortBy });
    downloadBlob(`${exportBasename}.svg`, new Blob([svg], { type: "image/svg+xml" }));
  }

  async function handleImport(file: File) {
    setPageError(null);
    try {
      const parsed = JSON.parse(await file.text()) as Partial<Layer>;
      if (!parsed || !Array.isArray(parsed.techniques)) {
        throw new Error("Not a valid ATT&CK layer file (missing techniques array).");
      }
      // Strip any saved-id the file carries and detach from ?saved — saving
      // an import should create a new entry, not overwrite the one that
      // happened to be open (or the one the file was exported from).
      const { tfm_saved_id: _ignored, ...rest } = parsed as Layer;
      setBaseLayer({ ...DEFAULT_BASE, ...rest });
      setState(layerToState(parsed as Layer));
      if (typeof parsed.name === "string" && parsed.name) setTitle(parsed.name);
      setSource("imported");
      if (savedId) setSearchParams({}, { replace: true });
    } catch (err) {
      setPageError(`Import failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  // Save to the library: update the entry being edited (?saved id, or the
  // current layer's stamped history id), else create a new entry.
  async function handleSave() {
    const name = title.trim() || "ATT&CK matrix";
    const base = baseLayer ?? DEFAULT_BASE;
    const layerJson = stateToLayer(state, { ...base, name });
    setSaveStatus("saving");
    setPageError(null);
    try {
      const targetId = savedId ?? base.tfm_saved_id ?? null;
      const entry = targetId
        ? await updateSavedMatrix(targetId, name, layerJson)
        : await createSavedMatrix(name, layerJson);
      setBaseLayer(entry.layer);
      setSource("saved");
      if (savedId !== entry.id) setSearchParams({ saved: entry.id }, { replace: true });
      setSaveStatus("saved");
      window.setTimeout(() => setSaveStatus("idle"), 1800);
    } catch (err) {
      setSaveStatus("idle");
      setPageError(`Save failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <div className="panel-header" style={{ justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flex: 1, minWidth: 0 }}>
          <Link to="/" className="btn" style={{ padding: "0.3rem 0.6rem", fontSize: "0.78rem" }}>
            ← Dashboard
          </Link>
          <input
            type="text"
            className="matrix-title-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Matrix title…"
            aria-label="Matrix title"
            title="Matrix title — used in the library and exports"
          />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <button
            className="btn btn-primary"
            style={{ padding: "0.3rem 0.7rem", fontSize: "0.78rem" }}
            onClick={() => void handleSave()}
            disabled={saveStatus === "saving"}
            title="Save this matrix to the library"
          >
            {saveStatus === "saving" ? "Saving…" : saveStatus === "saved" ? "Saved ✓" : "Save"}
          </button>
          <MatrixHistoryMenu label="History" />
          <label className="matrix-sort">
            Sort
            <select value={sortBy} onChange={(e) => setSortBy(e.target.value as TechniqueSort)}>
              <option value="default">Default order</option>
              <option value="score">Score (high → low)</option>
              <option value="name">Name (A → Z)</option>
            </select>
          </label>
          <MatrixMenu
            mappedCount={Object.keys(state).length}
            onExport={() => downloadJson(`${exportBasename}.json`, stateToLayer(state, exportBase()))}
            onExportSvg={handleExportSvg}
            onImport={handleImport}
            onClear={() => setState({})}
          />
        </div>
      </div>

      {pageError && (
        <div className="matrix-import-error">
          {pageError}
          <button onClick={() => setPageError(null)} aria-label="Dismiss">
            ×
          </button>
        </div>
      )}

      <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
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
        {catalog && <AttackMatrix catalog={catalog} layer={state} onLayerChange={setState} sortBy={sortBy} />}
      </div>
    </div>
  );
}
