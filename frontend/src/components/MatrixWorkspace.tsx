import { useEffect, useRef, useState, type ReactNode } from "react";
import { createSavedMatrix, updateSavedMatrix } from "../api/client";
import AttackMatrix from "./AttackMatrix";
import MatrixHistoryMenu from "./MatrixHistoryMenu";
import MatrixMenu from "./MatrixMenu";
import MatrixOverview from "./MatrixOverview";
import { useHeatTheme } from "../theme/heatThemes";
import {
  layerToState,
  stateToLayer,
  type Catalog,
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

interface MatrixWorkspaceProps {
  catalog: Catalog;
  /** Layer the grid is (re)initialized from. The grid resets whenever this
   * prop changes identity to a non-null value — pass null while nothing is
   * loaded (or to leave an import in place; see MatrixPage). */
  layer: Layer | null;
  /** Save target that wins over the layer's own tfm_saved_id stamp (the
   * matrix page's ?saved id). */
  saveTargetId?: string | null;
  /** Grid layout: "full" (default) is the wide, natural-size grid that
   * scrolls horizontally; "overview" is the dashboard's fit-to-width render
   * where all tactics are visible with no horizontal scroll (still fully
   * editable — cells open the editor popover). */
  variant?: "full" | "overview";
  /** Rendered before the title input — back/navigation buttons. */
  leading?: ReactNode;
  /** The user imported a layer file: the grid detached from whatever entry it
   * was showing (any tfm_saved_id in the file is stripped, so saving an
   * import always creates a new entry). */
  onImported?: () => void;
  /** A save landed on this library entry id (updated or newly created). */
  onSavedEntry?: (id: string) => void;
}

/** The full matrix editor — title, save-to-library, sort, import/export menu,
 * editable grid. Shared by the /matrix page and the dashboard's post-run view
 * so there's exactly one editor implementation. */
export default function MatrixWorkspace({
  catalog,
  layer,
  saveTargetId = null,
  variant = "full",
  leading,
  onImported,
  onSavedEntry,
}: MatrixWorkspaceProps) {
  const { theme } = useHeatTheme();
  const [state, setState] = useState<LayerState>({});
  const [title, setTitle] = useState("ATT&CK matrix");
  const [sortBy, setSortBy] = useState<TechniqueSort>("default");
  const [pageError, setPageError] = useState<string | null>(null);
  // Metadata (versions/domain/tfm_saved_id) of whatever the grid was loaded
  // from — the base every export and save is built on.
  const [baseLayer, setBaseLayer] = useState<Layer | null>(null);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved">("idle");

  // (Re)initialize from the layer prop — by identity, so internal edits and
  // imports are never clobbered by a re-render with the same object.
  const loadedRef = useRef<Layer | null>(null);
  useEffect(() => {
    if (layer && layer !== loadedRef.current) {
      loadedRef.current = layer;
      setBaseLayer(layer);
      setState(layerToState(layer));
      setTitle(layer.name || "ATT&CK matrix");
    }
  }, [layer]);

  const exportBasename = (title.trim() || "attack_matrix").replace(/\s+/g, "_");

  function exportBase(): Layer {
    return { ...(baseLayer ?? DEFAULT_BASE), name: title.trim() || "ATT&CK matrix" };
  }

  function handleExportSvg() {
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
      // Strip any saved-id the file carries — saving an import should create
      // a new entry, not overwrite the one that happened to be open (or the
      // one the file was exported from).
      const { tfm_saved_id: _ignored, ...rest } = parsed as Layer;
      setBaseLayer({ ...DEFAULT_BASE, ...rest });
      setState(layerToState(parsed as Layer));
      if (typeof parsed.name === "string" && parsed.name) setTitle(parsed.name);
      onImported?.();
    } catch (err) {
      setPageError(`Import failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  // Save to the library: update the entry being edited (?saved id, or the
  // layer's stamped history id), else create a new entry.
  async function handleSave() {
    const name = title.trim() || "ATT&CK matrix";
    const base = baseLayer ?? DEFAULT_BASE;
    const layerJson = stateToLayer(state, { ...base, name });
    setSaveStatus("saving");
    setPageError(null);
    try {
      const targetId = saveTargetId ?? base.tfm_saved_id ?? null;
      const entry = targetId
        ? await updateSavedMatrix(targetId, name, layerJson)
        : await createSavedMatrix(name, layerJson);
      setBaseLayer(entry.layer);
      setSaveStatus("saved");
      window.setTimeout(() => setSaveStatus("idle"), 1800);
      onSavedEntry?.(entry.id);
    } catch (err) {
      setSaveStatus("idle");
      setPageError(`Save failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <div className="panel-header" style={{ justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flex: 1, minWidth: 0 }}>
          {leading}
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
        {variant === "overview" ? (
          <MatrixOverview catalog={catalog} layer={state} onLayerChange={setState} sortBy={sortBy} />
        ) : (
          <AttackMatrix catalog={catalog} layer={state} onLayerChange={setState} sortBy={sortBy} />
        )}
      </div>
    </div>
  );
}
