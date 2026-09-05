import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
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

type CellTransition = "enter" | "exit";

// Must match the CSS animation durations for .attack-matrix__cell--entering /
// --exiting (index.css) — the timers below hold a removed cell's last known
// entry on screen for exactly as long as its fade-out plays.
const ENTER_MS = 420;
const EXIT_MS = 420;

/** Diffs `layer` against its previous value and returns (a) a map of
 * technique id -> "enter"/"exit" for whichever ids were just added or removed
 * — driving the phase-in/phase-out CSS classes on TechniqueCell — and (b) a
 * display layer that still includes a just-removed id's last entry for the
 * duration of its exit animation, merged under the real layer, so a technique
 * dropped by the FP-filtering pass fades out instead of vanishing instantly.
 * A technique newly appearing (a live mapping run) gets the same treatment in
 * reverse: it's already in `layer`, it just also gets the "enter" class. */
function useLayerTransitions(layer: LayerState): { transitions: Record<string, CellTransition>; displayLayer: LayerState } {
  const prevLayerRef = useRef<LayerState>(layer);
  const [transitions, setTransitions] = useState<Record<string, CellTransition>>({});
  const [exitingEntries, setExitingEntries] = useState<LayerState>({});
  const timersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  useEffect(() => {
    const prev = prevLayerRef.current;
    prevLayerRef.current = layer;
    if (prev === layer) return;

    const added = Object.keys(layer).filter((id) => !(id in prev));
    const removed = Object.keys(prev).filter((id) => !(id in layer));
    if (added.length === 0 && removed.length === 0) return;

    if (added.length) {
      setTransitions((t) => {
        const next = { ...t };
        for (const id of added) next[id] = "enter";
        return next;
      });
    }
    if (removed.length) {
      setExitingEntries((e) => {
        const next = { ...e };
        for (const id of removed) next[id] = prev[id];
        return next;
      });
      setTransitions((t) => {
        const next = { ...t };
        for (const id of removed) next[id] = "exit";
        return next;
      });
    }

    for (const id of added) {
      clearTimeout(timersRef.current[id]);
      timersRef.current[id] = setTimeout(() => {
        setTransitions((t) => {
          if (t[id] !== "enter") return t;
          const next = { ...t };
          delete next[id];
          return next;
        });
        delete timersRef.current[id];
      }, ENTER_MS);
    }
    for (const id of removed) {
      clearTimeout(timersRef.current[id]);
      timersRef.current[id] = setTimeout(() => {
        setExitingEntries((e) => {
          const next = { ...e };
          delete next[id];
          return next;
        });
        setTransitions((t) => {
          if (t[id] !== "exit") return t;
          const next = { ...t };
          delete next[id];
          return next;
        });
        delete timersRef.current[id];
      }, EXIT_MS);
    }
  }, [layer]);

  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      Object.values(timers).forEach(clearTimeout);
    };
  }, []);

  const displayLayer = useMemo(() => ({ ...exitingEntries, ...layer }), [exitingEntries, layer]);
  return { transitions, displayLayer };
}

interface AttackMatrixProps {
  catalog: Catalog;
  layer: LayerState;
  /** Editable when provided: cells open the score/comment editor and the
   * toolbar and tactic hide-menus appear. Without it, cells that are in the
   * layer open a read-only evidence popover instead. */
  onLayerChange?: (next: LayerState) => void;
  /** Vertical order of techniques within each tactic column. */
  sortBy?: TechniqueSort;
}

/** The matrix grid, laid out fit-to-width: tactic columns share the available
 * width equally, so all of them are visible with no horizontal scroll and only
 * the vertical axis scrolls. */
export default function AttackMatrix({
  catalog,
  layer,
  onLayerChange,
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
  const editable = Boolean(onLayerChange);
  const normalizedQuery = query.trim().toLowerCase();
  const mappedCount = Object.keys(layer).length;
  const { transitions, displayLayer } = useLayerTransitions(layer);

  // Close any open popover when anything scrolls (the anchored cell moves).
  // Capture phase because scroll events don't bubble — this catches the grid's
  // own scroll and its wrapper's scroll alike. Scrolls that
  // originate *inside* the popover (the evidence comment has its own
  // scrollbar) don't move the anchor, so they must not close it.
  useEffect(() => {
    if (!selected && !tacticMenu) return;
    const close = (e: Event) => {
      const target = e.target;
      if (target instanceof Element && target.closest(".attack-matrix__popover")) return;
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
    <div className="attack-matrix attack-matrix--overview">
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

      <div className="attack-matrix__grid">
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
                {sortTechniques(visible, displayLayer, sortBy).map((tech) => (
                  <TechniqueGroup
                    key={tech.id}
                    tech={tech}
                    layer={displayLayer}
                    transitions={transitions}
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
  transitions: Record<string, CellTransition>;
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
  transitions,
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

  // The sub-technique cluster needs to stay mounted for the whole collapse
  // animation to play (see .attack-matrix__subgroup-wrap in index.css — its
  // grid-rows transition animates against the content's real height, so
  // removing the content mid-collapse would just snap it shut). Rather than
  // mounting every group's sub-cells unconditionally, mount them once this
  // group is opened for the first time and leave them mounted after that —
  // groups never opened in this session cost nothing.
  const [everOpened, setEverOpened] = useState(isExpanded);
  useEffect(() => {
    if (isExpanded) setEverOpened(true);
  }, [isExpanded]);

  return (
    <div className={`attack-matrix__group${isExpanded && hasSubtechniques ? " attack-matrix__group--open" : ""}`}>
      <TechniqueCell
        id={tech.id}
        name={tech.name}
        url={tech.url}
        entry={layer[tech.id]}
        transition={transitions[tech.id]}
        theme={theme}
        editable={editable}
        isSelected={selected === tech.id}
        onOpenCell={onOpenCell}
        subCount={hasSubtechniques ? tech.subtechniques.length : undefined}
        expanded={hasSubtechniques ? isExpanded : undefined}
        onToggleExpand={hasSubtechniques ? onToggleExpand : undefined}
      />
      {hasSubtechniques && (
        <div className={`attack-matrix__subgroup-wrap${isExpanded ? " attack-matrix__subgroup-wrap--open" : ""}`}>
          <div className="attack-matrix__subgroup-inner">
            {everOpened && (
              <div className="attack-matrix__subgroup">
                {visibleSubs.map((sub) => (
                  <TechniqueCell
                    key={sub.id}
                    id={sub.id}
                    name={sub.name}
                    url={sub.url}
                    entry={layer[sub.id]}
                    transition={transitions[sub.id]}
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
        </div>
      )}
    </div>
  );
}

interface TechniqueCellProps {
  id: string;
  name: string;
  url: string;
  entry?: { score: number; comment?: string; flagged?: boolean };
  /** "enter" briefly after this technique first appears in the layer (a
   * mapping run just scored it), "exit" while it fades out after being
   * dropped (e.g. by the verification pass removing a low-confidence
   * finding). */
  transition?: CellTransition;
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
  transition,
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
    entry?.flagged && "attack-matrix__cell--flagged",
    transition === "enter" && "attack-matrix__cell--entering",
    transition === "exit" && "attack-matrix__cell--exiting",
  ]
    .filter(Boolean)
    .join(" ");

  const scoredStyle = entry
    ? { background: scoreToColor(entry.score, theme), color: readableTextColor(entry.score, theme) }
    : undefined;

  // When editable, every cell (parents included) opens the editor — expanding
  // lives on the caret button. When read-only, a cell that's in the layer opens
  // the evidence popover; otherwise clicking a parent expands it, so
  // sub-techniques stay viewable there too.
  function activate(el: HTMLElement) {
    if (editable || entry) onOpenCell(id, el);
    else if (hasSubs) onToggleExpand!();
  }

  const interactive = editable || hasSubs || Boolean(entry);

  return (
    <div
      className={classes}
      style={scoredStyle}
      title={`${id} · ${name}${entry ? ` — score ${entry.score}` : ""}${entry?.flagged ? " (flagged for review)" : ""}`}
      onClick={interactive ? (e) => activate(e.currentTarget) : undefined}
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : -1}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key !== "Enter" && e.key !== " ") return;
              e.preventDefault();
              activate(e.currentTarget);
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
    function onDown(e: MouseEvent) {
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
  entry?: { score: number; comment?: string; flagged?: boolean };
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
      {entry?.flagged && (
        <span className="badge badge-warning" title="A verification check on this technique's evidence didn't hold up — kept, but worth a second look">
          Flagged for review
        </span>
      )}
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
  entry: { score: number; comment?: string; flagged?: boolean };
  anchorRect: DOMRect;
  onClose: () => void;
}) {
  return (
    <AnchoredPopover anchorRect={anchorRect} width={400} onClose={onClose} className="attack-matrix__editor">
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
        {entry.flagged && (
          <span className="badge badge-warning" title="A verification check on this technique's evidence didn't hold up — kept, but worth a second look">
            Flagged for review
          </span>
        )}
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
