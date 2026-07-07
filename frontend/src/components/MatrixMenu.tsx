import { useEffect, useRef, useState } from "react";
import { HEAT_THEMES, cssGradient, themeById, useHeatTheme } from "../theme/heatThemes";

interface MatrixMenuProps {
  mappedCount: number;
  onExport: () => void;
  onExportSvg: () => void;
  onImport: (file: File) => void;
  onClear: () => void;
}

export default function MatrixMenu({ mappedCount, onExport, onExportSvg, onImport, onClear }: MatrixMenuProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const { theme, setThemeId } = useHeatTheme();

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="matrix-menu" ref={ref}>
      <button className="btn" onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open}>
        Menu ▾
      </button>
      <input
        type="file"
        accept="application/json,.json"
        ref={fileRef}
        style={{ display: "none" }}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onImport(file);
          e.target.value = ""; // allow re-importing the same file
        }}
      />

      {open && (
        <div className="matrix-menu__dropdown" role="menu">
          <button
            className="matrix-menu__item"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              fileRef.current?.click();
            }}
          >
            Import layer (JSON)…
          </button>
          <button
            className="matrix-menu__item"
            role="menuitem"
            disabled={mappedCount === 0}
            onClick={() => {
              setOpen(false);
              onExport();
            }}
          >
            Export layer (JSON)
          </button>
          <button
            className="matrix-menu__item"
            role="menuitem"
            disabled={mappedCount === 0}
            onClick={() => {
              setOpen(false);
              onExportSvg();
            }}
          >
            Export matrix (SVG)
          </button>
          <button
            className="matrix-menu__item matrix-menu__item--danger"
            role="menuitem"
            disabled={mappedCount === 0}
            onClick={() => {
              setOpen(false);
              onClear();
            }}
          >
            Clear all ({mappedCount})
          </button>

          <div className="matrix-menu__separator" />
          <div className="matrix-menu__label">Color theme</div>
          <div className="matrix-menu__themes">
            {HEAT_THEMES.map((t) => (
              <button
                key={t.id}
                className={`matrix-menu__theme${t.id === theme.id ? " matrix-menu__theme--active" : ""}`}
                onClick={() => setThemeId(t.id)}
                title={t.name}
                aria-pressed={t.id === theme.id}
              >
                <span className="matrix-menu__theme-swatch" style={{ background: cssGradient(themeById(t.id)) }} />
                {t.name}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
