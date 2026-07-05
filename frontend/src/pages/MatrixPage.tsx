import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import AttackMatrix from "../components/AttackMatrix";
import MatrixMenu from "../components/MatrixMenu";
import { useAttackData } from "../hooks/useAttackData";
import { layerToState, stateToLayer, type Layer, type LayerState } from "../types/attack";

function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function MatrixPage() {
  const { catalog, layer, loading, error } = useAttackData();
  const [state, setState] = useState<LayerState>({});
  const [importError, setImportError] = useState<string | null>(null);

  useEffect(() => {
    if (layer) setState(layerToState(layer));
  }, [layer]);

  async function handleImport(file: File) {
    setImportError(null);
    try {
      const parsed = JSON.parse(await file.text()) as Partial<Layer>;
      if (!parsed || !Array.isArray(parsed.techniques)) {
        throw new Error("Not a valid ATT&CK layer file (missing techniques array).");
      }
      setState(layerToState(parsed as Layer));
    } catch (err) {
      setImportError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <div className="panel-header" style={{ justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <Link to="/" className="btn" style={{ padding: "0.3rem 0.6rem", fontSize: "0.78rem" }}>
            ← Dashboard
          </Link>
          <h2 style={{ margin: 0 }}>Full ATT&amp;CK Matrix</h2>
        </div>
        <MatrixMenu
          mappedCount={Object.keys(state).length}
          onExport={() =>
            layer && downloadJson(`${layer.name.replace(/\s+/g, "_")}.json`, stateToLayer(state, layer))
          }
          onImport={handleImport}
          onClear={() => setState({})}
        />
      </div>

      {importError && (
        <div className="matrix-import-error">
          Import failed: {importError}
          <button onClick={() => setImportError(null)} aria-label="Dismiss">
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
        {catalog && <AttackMatrix catalog={catalog} layer={state} onLayerChange={setState} />}
      </div>
    </div>
  );
}
