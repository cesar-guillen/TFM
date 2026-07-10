import { useCallback, useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import {
  sortSubtechniques,
  sortTechniques,
  type Catalog,
  type CatalogTechnique,
  type LayerState,
  type TechniqueSort,
  type TechniqueSummary,
} from "../types/attack";
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
  /** Fit-to-width layout: columns share the available width equally so all
   * tactics are visible with no horizontal scroll (this is the only layout
   * rendered anywhere since the wide grid was retired). Layout only — the
   * toolbar, tactic hide-menus and cell editor follow `onLayerChange`. */
  overview?: boolean;
  /** Vertical order of techniques within each tactic column. */
  sortBy?: TechniqueSort;
}

export default function AttackMatrix({
  catalog,
  layer,
  onLayerChange,
  compact = false,
  overview = false,
  sortBy = "default",
}: AttackMatrixProps) {
  const { theme } = useHeatTheme();
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [hiddenTactics, setHiddenTactics] = useState<Set<string>>(new Set());
  const [showHiddenList, setShowHiddenList] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  const [tacticMenu, setTacticMenu] = useState<{ id: string; name: string; rect: DOMRect } | null>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);
  const gridRef = useRef<HTMLDivElement>(null);
  const editable = Boolean(onLayerChange);
  const normalizedQuery = query.trim().toLowerCase();
  const mappedCount = Object.keys(layer).length;

  // Side-scroll arrows for the full matrix (the overview preview fits its
  // full width with no side-scroll — see .attack-matrix--overview).
  const syncScrollArrows = useCallback(() => {
    const el = gridRef.current;
    if (!el) return;
    const maxScroll = el.scrollWidth - el.clientWidth;
    setCanScrollLeft(el.scrollLeft > 1);
    setCanScrollRight(el.scrollLeft < maxScroll - 1);
  }, []);

  useLayoutEffect(() => {
    if (overview) return;
    syncScrollArrows();
  }, [overview, syncScrollArrows, hiddenTactics, normalizedQuery]);

  useEffect(() => {
    if (overview) return;
    const el = gridRef.current;
    if (!el) return;
    el.addEventListener("scroll", syncScrollArrows, { passive: true });
    const ro = new ResizeObserver(syncScrollArrows);
    ro.observe(el);
    return () => {
      el.removeEventListener("scroll", syncScrollArrows);
      ro.disconnect();
    };
  }, [overview, syncScrollArrows]);

  // Scroll to an explicit, clamped target rather than a relative scrollBy —
  // clicking a few times fast can't overshoot past the last column and
  // "leave the matrix behind" this way, since every click recomputes the
  // bound fresh instead of compounding on top of a possibly still-animating
  // position.
  function pageGrid(direction: 1 | -1) {
    const el = gridRef.current;
    if (!el) return;
    const maxScroll = el.scrollWidth - el.clientWidth;
    const target = Math.max(0, Math.min(maxScroll, el.scrollLeft + direction * el.clientWidth * 0.8));
    el.scrollTo({ left: target, behavior: "smooth" });
  }

  // Close any open popover when anything scrolls (the anchored cell moves).
  // Capture phase because scroll events don't bubble — this catches the grid's
  // own scroll and the overview preview's wrapper scroll alike.
  useEffect(() => {
    if (!selected && !tacticMenu) return;
    const close = () => {
      setSelected(null);
      setTacticMenu(null);
    };
    document.addEventListener("scroll", close, { capture: true, passive: true });
    return () => document.removeEventListener("scroll", close, { capture: true });
  }, [selected, tacticMenu]);

  function toggleExpanded(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // Editable: opens the score/comment editor. Read-only (dashboard run view):
  // opens the evidence popover for cells that are in the layer.
  function openCell(id: string, el: HTMLElement) {
    if (!onLayerChange && !layer[id]) return;
    setSelected(id);
    setAnchorRect(el.getBoundingClientRect());
  }

  // Upsert: opening the editor doesn't touch the layer — an entry is only
  // created once the user actually sets a score or comment.
  function updateEntry(id: string, patch: Partial<{ score: number; comment: string }>) {
    if (!onLayerChange) return;
    const base = layer[id] ?? { score: 0 };
    onLayerChange({ ...layer, [id]: { ...base, ...patch } });
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

  // Every technique that owns sub-techniques — used by the expand/collapse-all toggle.
  const expandableIds = catalog.tactics.flatMap((t) =>
    t.techniques.filter((tech) => tech.subtechniques.length > 0).map((tech) => tech.id)
  );
  const allExpanded = expandableIds.length > 0 && expandableIds.every((id) => expanded.has(id));

  function toggleExpandAll() {
    setExpanded(allExpanded ? new Set() : new Set(expandableIds));
  }

  return (
    <div
      className={`attack-matrix${compact ? " attack-matrix--compact" : ""}${overview ? " attack-matrix--overview" : ""}`}
    >
      {editable && (
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
        {expandableIds.length > 0 && (
          <button className="btn attack-matrix__expand-all" onClick={toggleExpandAll}>
            {allExpanded ? "Collapse all" : "Expand all"}
          </button>
        )}
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
              {!editable ? (
                <div className="attack-matrix__column-header attack-matrix__column-header--static" title={tactic.name}>
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
                {sortTechniques(visible, layer, sortBy).map((tech) => (
                  <TechniqueGroup
                    key={tech.id}
                    tech={tech}
                    layer={layer}
                    theme={theme}
                    editable={editable}
                    selected={selected}
                    forceExpand={Boolean(normalizedQuery) && tech.subtechniques.some((s) => matchesQuery(s, normalizedQuery))}
                    expanded={expanded.has(tech.id)}
                    onToggleExpand={() => toggleExpanded(tech.id)}
                    onOpenCell={openCell}
                    query={normalizedQuery}
                    sortBy={sortBy}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {!overview && (
        <>
          <button
            className="attack-matrix__arrow attack-matrix__arrow--left"
            onClick={() => pageGrid(-1)}
            disabled={!canScrollLeft}
            aria-label="Scroll matrix left"
          >
            ‹
          </button>
          <button
            className="attack-matrix__arrow attack-matrix__arrow--right"
            onClick={() => pageGrid(1)}
            disabled={!canScrollRight}
            aria-label="Scroll matrix right"
          >
            ›
          </button>
        </>
      )}

      {tacticMenu && (
        <AnchoredPopover anchorRect={tacticMenu.rect} onClose={() => setTacticMenu(null)} width={180}>
          <div className="attack-matrix__tactic-menu-title">{tacticMenu.name}</div>
          <button className="matrix-menu__item" onClick={() => hideTactic(tacticMenu.id)}>
            Hide this tactic
          </button>
        </AnchoredPopover>
      )}

      {editable && selectedTech && anchorRect && (
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

      {!editable && selectedTech && selectedEntry && anchorRect && (
        <CellDetails
          tech={selectedTech}
          entry={selectedEntry}
          anchorRect={anchorRect}
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
  selected: string | null;
  expanded: boolean;
  forceExpand: boolean;
  onToggleExpand: () => void;
  onOpenCell: (id: string, el: HTMLElement) => void;
  query: string;
  sortBy: TechniqueSort;
}

function TechniqueGroup({
  tech,
  layer,
  theme,
  editable,
  selected,
  expanded,
  forceExpand,
  onToggleExpand,
  onOpenCell,
  query,
  sortBy,
}: TechniqueGroupProps) {
  const hasSubtechniques = tech.subtechniques.length > 0;
  const isExpanded = expanded || forceExpand;
  const visibleSubs = sortSubtechniques(
    tech.subtechniques.filter((s) => matchesQuery(s, query)),
    layer,
    sortBy
  );

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
        onOpenCell={onOpenCell}
        subCount={hasSubtechniques ? tech.subtechniques.length : undefined}
        expanded={hasSubtechniques ? isExpanded : undefined}
        onToggleExpand={hasSubtechniques ? onToggleExpand : undefined}
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
              onOpenCell={onOpenCell}
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
  onOpenCell: (id: string, el: HTMLElement) => void;
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
  onOpenCell,
  sub,
  subCount,
  expanded,
  onToggleExpand,
}: TechniqueCellProps) {
  const hasSubs = onToggleExpand !== undefined;
  const classes = [
    "attack-matrix__cell",
    sub && "attack-matrix__cell--sub",
    isSelected && "attack-matrix__cell--selected",
    (editable || hasSubs || entry) && "attack-matrix__cell--interactive",
    entry && "attack-matrix__cell--scored",
  ]
    .filter(Boolean)
    .join(" ");

  const scoredStyle = entry
    ? { background: scoreToColor(entry.score, theme), color: readableTextColor(entry.score, theme) }
    : undefined;

  // Primary click: when editable, every cell (parents included) opens the editor —
  // expand/collapse lives on the caret button. When not editable (dashboard run
  // view / preview), a cell that's in the layer opens the read-only evidence
  // popover; otherwise clicking a parent expands it so sub-techniques are
  // still viewable.
  function handleClick(e: MouseEvent<HTMLDivElement>) {
    if (editable || entry) onOpenCell(id, e.currentTarget);
    else if (hasSubs) onToggleExpand!();
  }

  const interactive = editable || hasSubs || Boolean(entry);

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
                if (editable || entry) onOpenCell(id, e.currentTarget);
                else if (hasSubs) onToggleExpand!();
              }
            }
          : undefined
      }
    >
      <div className="attack-matrix__cell-meta">
        {hasSubs && (
          <button
            type="button"
            className={`attack-matrix__caret${expanded ? " attack-matrix__caret--open" : ""}`}
            title={expanded ? "Collapse sub-techniques" : "Expand sub-techniques"}
            aria-label={expanded ? "Collapse sub-techniques" : "Expand sub-techniques"}
            aria-expanded={expanded}
            onClick={(e) => {
              e.stopPropagation();
              onToggleExpand!();
            }}
          >
            ▸
          </button>
        )}
        <span className="attack-matrix__cell-id">{id}</span>
        {subCount !== undefined && <span className="attack-matrix__sub-count">{subCount}</span>}
        <span className="attack-matrix__cell-spacer" />
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
  /** Absent while the technique isn't in the layer yet — the editor shows
   * defaults and the first change creates the entry. */
  entry?: { score: number; comment?: string };
  anchorRect: DOMRect;
  onScore: (score: number) => void;
  onComment: (comment: string) => void;
  onRemove: () => void;
  onClose: () => void;
}

function CellEditor({ tech, entry, anchorRect, onScore, onComment, onRemove, onClose }: CellEditorProps) {
  const score = entry?.score ?? 0;
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
          <input type="range" min={0} max={100} value={score} onChange={(e) => onScore(Number(e.target.value))} />
          <input
            type="number"
            min={0}
            max={100}
            value={score}
            onChange={(e) => onScore(Math.max(0, Math.min(100, Number(e.target.value))))}
          />
        </div>
      </label>
      <label className="attack-matrix__editor-field">
        <span>Comment</span>
        <textarea rows={3} value={entry?.comment ?? ""} onChange={(e) => onComment(e.target.value)} />
      </label>
      {entry && (
        <button className="btn btn-danger attack-matrix__editor-remove" onClick={onRemove}>
          Remove from matrix
        </button>
      )}
    </AnchoredPopover>
  );
}

/** Read-only counterpart of CellEditor for non-editable renders (the dashboard
 * run view): shows a mapped technique's score and the evidence comments the
 * mapper attached, so TTPs can be inspected while the run is still going. */
function CellDetails({
  tech,
  entry,
  anchorRect,
  onClose,
}: {
  tech: TechniqueSummary;
  entry: { score: number; comment?: string };
  anchorRect: DOMRect;
  onClose: () => void;
}) {
  return (
    <AnchoredPopover anchorRect={anchorRect} width={320} onClose={onClose} className="attack-matrix__editor">
      <div className="attack-matrix__editor-header">
        <div>
          <strong>{tech.id}</strong>
          <span>{tech.name}</span>
        </div>
        <button className="attack-matrix__editor-close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>
      <div className="attack-matrix__details-score">
        <span className="badge">score {entry.score}</span>
        <a href={tech.url} target="_blank" rel="noreferrer" title={`Open ${tech.id} on attack.mitre.org`}>
          attack.mitre.org ↗
        </a>
      </div>
      <div className="attack-matrix__details-comment">
        {entry.comment?.trim() || "No evidence comment on this technique."}
      </div>
    </AnchoredPopover>
  );
}
