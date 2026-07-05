import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import type { Catalog, CatalogTechnique, LayerState, TechniqueSummary } from "../types/attack";
import { cssGradient, readableTextColor, scoreToColor, useHeatTheme, type HeatTheme } from "../theme/heatThemes";

function matchesQuery(t: TechniqueSummary, query: string): boolean {
  if (!query) return true;
  return t.id.toLowerCase().includes(query) || t.name.toLowerCase().includes(query);
}

function findTechnique(catalog: Catalog, id: string): TechniqueSummary | undefined {
  for (const tactic of catalog.tactics) {
    for (const tech of tactic.techniques) {
      if (tech.id === id) return tech;
      const sub = tech.subtechniques.find((s) => s.id === id);
      if (sub) return sub;
    }
  }
  return undefined;
}

interface AttackMatrixProps {
  catalog: Catalog;
  layer: LayerState;
  onLayerChange?: (next: LayerState) => void;
  compact?: boolean;
  /** Static, scaled-to-fit render: no toolbar, no expand/hide interactions.
   * The whole matrix lays out at natural size so a parent can scale it. */
  overview?: boolean;
}

export default function AttackMatrix({ catalog, layer, onLayerChange, compact = false, overview = false }: AttackMatrixProps) {
  const { theme } = useHeatTheme();
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [hiddenTactics, setHiddenTactics] = useState<Set<string>>(new Set());
  const [showHiddenList, setShowHiddenList] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  const [tacticMenu, setTacticMenu] = useState<{ id: string; name: string; rect: DOMRect } | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const editable = Boolean(onLayerChange);
  const normalizedQuery = query.trim().toLowerCase();
  const mappedCount = Object.keys(layer).length;

  // Close the editor popover when the grid scrolls (the anchored cell moves).
  useEffect(() => {
    const grid = gridRef.current;
    if (!grid || (!selected && !tacticMenu)) return;
    const close = () => {
      setSelected(null);
      setTacticMenu(null);
    };
    grid.addEventListener("scroll", close, { passive: true });
    return () => grid.removeEventListener("scroll", close);
  }, [selected, tacticMenu]);

  function toggleExpanded(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function openEditor(id: string, el: HTMLElement) {
    if (!onLayerChange) return;
    setSelected(id);
    setAnchorRect(el.getBoundingClientRect());
    if (!layer[id]) onLayerChange({ ...layer, [id]: { score: 100 } });
  }

  function updateEntry(id: string, patch: Partial<{ score: number; comment: string }>) {
    if (!onLayerChange || !layer[id]) return;
    onLayerChange({ ...layer, [id]: { ...layer[id], ...patch } });
  }

  function removeEntry(id: string) {
    if (!onLayerChange) return;
    const next = { ...layer };
    delete next[id];
    onLayerChange(next);
    setSelected(null);
  }

  function hideTactic(id: string) {
    setHiddenTactics((prev) => new Set(prev).add(id));
    setTacticMenu(null);
  }

  function showTactic(id: string) {
    setHiddenTactics((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }

  const selectedTech = selected ? findTechnique(catalog, selected) : undefined;
  const selectedEntry = selected ? layer[selected] : undefined;
  const visibleTactics = catalog.tactics.filter((t) => !hiddenTactics.has(t.id));
  const hiddenList = catalog.tactics.filter((t) => hiddenTactics.has(t.id));

  return (
    <div
      className={`attack-matrix${compact ? " attack-matrix--compact" : ""}${overview ? " attack-matrix--overview" : ""}`}
    >
      {!overview && (
      <div className="attack-matrix__toolbar">
        <input
          type="text"
          className="text-input"
          placeholder="Search techniques..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="attack-matrix__legend">
          <span>0</span>
          <span className="attack-matrix__legend-swatch" style={{ background: cssGradient(theme) }} />
          <span>100</span>
        </div>
        {hiddenList.length > 0 && (
          <div className="attack-matrix__hidden">
            <button className="btn attack-matrix__hidden-btn" onClick={() => setShowHiddenList((v) => !v)}>
              {hiddenList.length} tactic{hiddenList.length > 1 ? "s" : ""} hidden ▾
            </button>
            {showHiddenList && (
              <div className="attack-matrix__hidden-menu">
                {hiddenList.map((t) => (
                  <button key={t.id} className="attack-matrix__hidden-item" onClick={() => showTactic(t.id)}>
                    <span>{t.name}</span>
                    <span className="attack-matrix__hidden-show">Show</span>
                  </button>
                ))}
                <button
                  className="attack-matrix__hidden-item attack-matrix__hidden-item--all"
                  onClick={() => {
                    setHiddenTactics(new Set());
                    setShowHiddenList(false);
                  }}
                >
                  Show all
                </button>
              </div>
            )}
          </div>
        )}
        {mappedCount > 0 && <span className="badge">{mappedCount} mapped</span>}
      </div>
      )}

      <div className="attack-matrix__grid" ref={gridRef}>
        {visibleTactics.map((tactic) => {
          const visible = tactic.techniques.filter(
            (t) => matchesQuery(t, normalizedQuery) || t.subtechniques.some((s) => matchesQuery(s, normalizedQuery))
          );
          if (normalizedQuery && visible.length === 0) return null;

          return (
            <div className="attack-matrix__column" key={tactic.id}>
              {overview ? (
                <div className="attack-matrix__column-header attack-matrix__column-header--static">
                  <span>{tactic.name}</span>
                  <span className="attack-matrix__column-count">{tactic.techniques.length}</span>
                </div>
              ) : (
                <button
                  className="attack-matrix__column-header"
                  title={`${tactic.name} — click to hide`}
                  onClick={(e) => setTacticMenu({ id: tactic.id, name: tactic.name, rect: e.currentTarget.getBoundingClientRect() })}
                >
                  <span>{tactic.name}</span>
                  <span className="attack-matrix__column-count">{tactic.techniques.length}</span>
                </button>
              )}
              <div className="attack-matrix__column-body">
                {visible.map((tech) => (
                  <TechniqueGroup
                    key={tech.id}
                    tech={tech}
                    layer={layer}
                    theme={theme}
                    editable={editable}
                    overview={overview}
                    selected={selected}
                    forceExpand={Boolean(normalizedQuery) && tech.subtechniques.some((s) => matchesQuery(s, normalizedQuery))}
                    expanded={expanded.has(tech.id)}
                    onToggleExpand={() => toggleExpanded(tech.id)}
                    onOpenEditor={openEditor}
                    query={normalizedQuery}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {tacticMenu && (
        <AnchoredPopover anchorRect={tacticMenu.rect} onClose={() => setTacticMenu(null)} width={180}>
          <div className="attack-matrix__tactic-menu-title">{tacticMenu.name}</div>
          <button className="matrix-menu__item" onClick={() => hideTactic(tacticMenu.id)}>
            Hide this tactic
          </button>
        </AnchoredPopover>
      )}

      {editable && selectedTech && selectedEntry && anchorRect && (
        <CellEditor
          tech={selectedTech}
          entry={selectedEntry}
          anchorRect={anchorRect}
          onScore={(score) => updateEntry(selectedTech.id, { score })}
          onComment={(comment) => updateEntry(selectedTech.id, { comment })}
          onRemove={() => removeEntry(selectedTech.id)}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}

interface TechniqueGroupProps {
  tech: CatalogTechnique;
  layer: LayerState;
  theme: HeatTheme;
  editable: boolean;
  overview: boolean;
  selected: string | null;
  expanded: boolean;
  forceExpand: boolean;
  onToggleExpand: () => void;
  onOpenEditor: (id: string, el: HTMLElement) => void;
  query: string;
}

function TechniqueGroup({
  tech,
  layer,
  theme,
  editable,
  overview,
  selected,
  expanded,
  forceExpand,
  onToggleExpand,
  onOpenEditor,
  query,
}: TechniqueGroupProps) {
  const hasSubtechniques = tech.subtechniques.length > 0;
  const isExpanded = !overview && (expanded || forceExpand);
  const visibleSubs = tech.subtechniques.filter((s) => matchesQuery(s, query));

  return (
    <div className={`attack-matrix__group${isExpanded && hasSubtechniques ? " attack-matrix__group--open" : ""}`}>
      <TechniqueCell
        id={tech.id}
        name={tech.name}
        url={tech.url}
        entry={layer[tech.id]}
        theme={theme}
        editable={editable}
        isSelected={selected === tech.id}
        onOpenEditor={onOpenEditor}
        subCount={hasSubtechniques ? tech.subtechniques.length : undefined}
        expanded={hasSubtechniques ? isExpanded : undefined}
        onToggleExpand={hasSubtechniques && !overview ? onToggleExpand : undefined}
      />
      {isExpanded && hasSubtechniques && (
        <div className="attack-matrix__subgroup">
          {visibleSubs.map((sub) => (
            <TechniqueCell
              key={sub.id}
              id={sub.id}
              name={sub.name}
              url={sub.url}
              entry={layer[sub.id]}
              theme={theme}
              editable={editable}
              isSelected={selected === sub.id}
              onOpenEditor={onOpenEditor}
              sub
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface TechniqueCellProps {
  id: string;
  name: string;
  url: string;
  entry?: { score: number; comment?: string };
  theme: HeatTheme;
  editable: boolean;
  isSelected: boolean;
  onOpenEditor: (id: string, el: HTMLElement) => void;
  sub?: boolean;
  subCount?: number;
  expanded?: boolean;
  onToggleExpand?: () => void;
}

function TechniqueCell({
  id,
  name,
  url,
  entry,
  theme,
  editable,
  isSelected,
  onOpenEditor,
  sub,
  subCount,
  expanded,
  onToggleExpand,
}: TechniqueCellProps) {
  const isParent = onToggleExpand !== undefined;
  const classes = [
    "attack-matrix__cell",
    sub && "attack-matrix__cell--sub",
    isSelected && "attack-matrix__cell--selected",
    (editable || isParent) && "attack-matrix__cell--interactive",
    entry && "attack-matrix__cell--scored",
  ]
    .filter(Boolean)
    .join(" ");

  const scoredStyle = entry
    ? { background: scoreToColor(entry.score, theme), color: readableTextColor(entry.score, theme) }
    : undefined;

  // Primary click: parents expand/collapse; leaves & sub-techniques open the editor.
  function handleClick(e: MouseEvent<HTMLDivElement>) {
    if (isParent) onToggleExpand!();
    else if (editable) onOpenEditor(id, e.currentTarget);
  }

  const interactive = editable || isParent;

  return (
    <div
      className={classes}
      style={scoredStyle}
      title={`${id} · ${name}${entry ? ` — score ${entry.score}` : ""}`}
      onClick={interactive ? handleClick : undefined}
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : -1}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                if (isParent) onToggleExpand!();
                else onOpenEditor(id, e.currentTarget);
              }
            }
          : undefined
      }
    >
      <div className="attack-matrix__cell-meta">
        {isParent && <span className={`attack-matrix__caret${expanded ? " attack-matrix__caret--open" : ""}`}>▸</span>}
        <span className="attack-matrix__cell-id">{id}</span>
        {subCount !== undefined && <span className="attack-matrix__sub-count">{subCount}</span>}
        <span className="attack-matrix__cell-spacer" />
        {isParent && editable && (
          <button
            className="attack-matrix__cell-edit"
            title="Score this technique"
            onClick={(e) => {
              e.stopPropagation();
              onOpenEditor(id, e.currentTarget.closest(".attack-matrix__cell") as HTMLElement);
            }}
          >
            ✎
          </button>
        )}
        <a
          className="attack-matrix__cell-link"
          href={url}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          title={`Open ${id} on attack.mitre.org`}
        >
          ↗
        </a>
      </div>
      <div className="attack-matrix__cell-name">{name}</div>
    </div>
  );
}

/** Fixed-position popover anchored beside a rect, clamped to the viewport,
 * closing on outside-click / Escape. Shared by the tactic menu and cell editor. */
function AnchoredPopover({
  anchorRect,
  width,
  onClose,
  children,
  className = "",
}: {
  anchorRect: DOMRect;
  width: number;
  onClose: () => void;
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: -9999, left: -9999 });

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const { height } = el.getBoundingClientRect();
    const gap = 8;
    let left = anchorRect.right + gap;
    if (left + width > window.innerWidth - gap) left = anchorRect.left - width - gap;
    if (left < gap) left = Math.max(gap, window.innerWidth - width - gap);
    let top = anchorRect.bottom + gap;
    if (top + height > window.innerHeight - gap) top = Math.max(gap, anchorRect.top - height - gap);
    if (top < gap) top = gap;
    setPos({ top, left });
  }, [anchorRect, width]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    function onDown(e: globalThis.MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [onClose]);

  return (
    <div className={`attack-matrix__popover ${className}`} ref={ref} style={{ top: pos.top, left: pos.left, width }}>
      {children}
    </div>
  );
}

interface CellEditorProps {
  tech: TechniqueSummary;
  entry: { score: number; comment?: string };
  anchorRect: DOMRect;
  onScore: (score: number) => void;
  onComment: (comment: string) => void;
  onRemove: () => void;
  onClose: () => void;
}

function CellEditor({ tech, entry, anchorRect, onScore, onComment, onRemove, onClose }: CellEditorProps) {
  return (
    <AnchoredPopover anchorRect={anchorRect} width={260} onClose={onClose} className="attack-matrix__editor">
      <div className="attack-matrix__editor-header">
        <div>
          <strong>{tech.id}</strong>
          <span>{tech.name}</span>
        </div>
        <button className="attack-matrix__editor-close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>
      <label className="attack-matrix__editor-field">
        <span>Score</span>
        <div className="attack-matrix__editor-score">
          <input type="range" min={0} max={100} value={entry.score} onChange={(e) => onScore(Number(e.target.value))} />
          <input
            type="number"
            min={0}
            max={100}
            value={entry.score}
            onChange={(e) => onScore(Math.max(0, Math.min(100, Number(e.target.value))))}
          />
        </div>
      </label>
      <label className="attack-matrix__editor-field">
        <span>Comment</span>
        <textarea rows={3} value={entry.comment ?? ""} onChange={(e) => onComment(e.target.value)} />
      </label>
      <button className="btn btn-danger attack-matrix__editor-remove" onClick={onRemove}>
        Remove from matrix
      </button>
    </AnchoredPopover>
  );
}
