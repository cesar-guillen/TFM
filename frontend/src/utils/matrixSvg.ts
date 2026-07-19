import { readableTextColor, scoreToColor, type HeatTheme } from "../theme/heatThemes";
import {
  sortSubtechniques,
  sortTechniques,
  type Catalog,
  type CatalogTechnique,
  type LayerState,
  type TechniqueSort,
  type TechniqueSummary,
} from "../types/attack";

/** Standalone SVG render of the matrix, for export (report/thesis figures).
 * Mirrors the on-screen grid in its dark theme — column panels with a tactic
 * header band, two-row cells (monospace ID above the full, wrapped name), and
 * flagged sub-techniques indented under their parent behind a connector rail;
 * scored cells use the active heat theme's ramp. Deliberately narrow columns
 * (the full 15-tactic grid must stay legible scaled to a report's page
 * width). Flagged sub-techniques are always shown regardless of on-screen
 * expansion state. */

const COL_W = 120; // narrower than on-screen: the export scales to page width
const COL_GAP = 6;
const COL_PAD = 4; // matches .attack-matrix__column-body padding
const CELL_GAP = 3;
const HEADER_H = 24;
const PAD = 16;
const TITLE_H = 40;
// Sub-technique cluster: rail + indent (≈ subgroup margin + padding on screen)
const RAIL_INDENT = 8;
const SUB_INDENT = 15;

// Cell internals
const CELL_PAD_X = 5;
const CELL_PAD_Y = 4;
const ID_FONT = 6.5;
const ID_ROW_H = 8;
const NAME_FONT = 8;
const SUB_NAME_FONT = 7.5;
const LINE_H = 10;
const MAX_NAME_LINES = 3;

const FONT = "font-family='Helvetica, Arial, sans-serif'";
const MONO_FONT = "font-family='Menlo, Consolas, monospace'";

// The app's dark theme (index.css :root), so the figure matches the UI.
const C = {
  pageBg: "#0b0e14", // --bg
  colBg: "#141924", // --bg-panel
  colBorder: "#232938", // --border
  headerBg: "#11151d", // --bg-raised
  headerText: "#8891a5", // --text-dim
  cellBg: "#11151d", // --bg-raised
  cellBorder: "#1b2130", // --border-soft
  cellName: "#e6e9f0", // --text
  cellId: "#5b6478", // --text-faint
  title: "#e6e9f0",
  faint: "#8891a5",
  rail: "#7c8cff", // --accent, like the on-screen subgroup rail
};

function esc(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Greedy word-wrap into at most `maxLines` lines (~0.54em per Helvetica
 * char); the last line is ellipsized when the text doesn't fit, and a single
 * word longer than a whole line is hard-broken with a hyphen. */
function wrapText(text: string, maxPx: number, fontSize: number, maxLines: number): string[] {
  const maxChars = Math.max(4, Math.floor(maxPx / (fontSize * 0.54)));
  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let line = "";
  for (let word of words) {
    while (word.length > maxChars) {
      if (line) {
        lines.push(line);
        line = "";
      }
      lines.push(word.slice(0, maxChars - 1) + "-");
      word = word.slice(maxChars - 1);
    }
    const candidate = line ? `${line} ${word}` : word;
    if (candidate.length <= maxChars) {
      line = candidate;
    } else {
      lines.push(line);
      line = word;
    }
  }
  if (line) lines.push(line);
  if (lines.length > maxLines) {
    const kept = lines.slice(0, maxLines);
    const last = kept[maxLines - 1];
    kept[maxLines - 1] = last.length >= maxChars ? last.slice(0, maxChars - 1) + "…" : last + "…";
    return kept;
  }
  return lines.length > 0 ? lines : [text];
}

interface CellRender {
  svg: string;
  height: number;
}

function renderCell(
  x: number,
  y: number,
  width: number,
  tech: TechniqueSummary,
  entry: { score: number } | undefined,
  theme: HeatTheme,
  sub: boolean
): CellRender {
  const nameFont = sub ? SUB_NAME_FONT : NAME_FONT;
  const lines = wrapText(tech.name, width - CELL_PAD_X * 2, nameFont, MAX_NAME_LINES);
  const height = CELL_PAD_Y + ID_ROW_H + lines.length * LINE_H + CELL_PAD_Y - 2;

  const fill = entry ? scoreToColor(entry.score, theme) : C.cellBg;
  const stroke = entry ? "none" : C.cellBorder;
  const nameColor = entry ? readableTextColor(entry.score, theme) : C.cellName;
  const idColor = entry ? nameColor : C.cellId;
  const idOpacity = entry ? " fill-opacity='0.75'" : "";

  let svg =
    `<rect x='${x}' y='${y}' width='${width}' height='${height}' rx='5' fill='${fill}'` +
    (stroke === "none" ? "" : ` stroke='${stroke}' stroke-width='1'`) +
    `/>` +
    `<text x='${x + CELL_PAD_X}' y='${y + CELL_PAD_Y + ID_FONT}' font-size='${ID_FONT}' ${MONO_FONT} ` +
    `fill='${idColor}'${idOpacity}>${esc(tech.id)}</text>`;
  lines.forEach((line, i) => {
    svg +=
      `<text x='${x + CELL_PAD_X}' y='${y + CELL_PAD_Y + ID_ROW_H + (i + 1) * LINE_H - 2.5}' ` +
      `font-size='${nameFont}' ${FONT} fill='${nameColor}'>${esc(line)}</text>`;
  });
  return { svg, height };
}

function renderColumn(
  tacticName: string,
  techniques: CatalogTechnique[],
  x: number,
  y: number,
  state: LayerState,
  theme: HeatTheme,
  sortBy: TechniqueSort,
  clipId: string
): { svg: string; height: number } {
  const innerX = x + COL_PAD;
  const innerW = COL_W - COL_PAD * 2;
  const cells: string[] = [];
  let cursor = y + HEADER_H + COL_PAD;

  for (const tech of sortTechniques(techniques, state, sortBy)) {
    const parent = renderCell(innerX, cursor, innerW, tech, state[tech.id], theme, false);
    cells.push(parent.svg);
    cursor += parent.height + CELL_GAP;

    const flaggedSubs = sortSubtechniques(
      tech.subtechniques.filter((s) => state[s.id]),
      state,
      sortBy
    );
    if (flaggedSubs.length > 0) {
      const railTop = cursor;
      for (const subTech of flaggedSubs) {
        const subCell = renderCell(innerX + SUB_INDENT, cursor, innerW - SUB_INDENT, subTech, state[subTech.id], theme, true);
        cells.push(subCell.svg);
        cursor += subCell.height + CELL_GAP;
      }
      // Connector rail bracketing the sub-cluster, like the on-screen subgroup.
      cells.push(
        `<rect x='${innerX + RAIL_INDENT}' y='${railTop}' width='2' height='${cursor - CELL_GAP - railTop}' ` +
          `rx='1' fill='${C.rail}'/>`
      );
    }
  }

  const height = cursor - CELL_GAP + COL_PAD - y;
  const svg =
    `<clipPath id='${clipId}'><rect x='${x}' y='${y}' width='${COL_W}' height='${height}' rx='8'/></clipPath>` +
    `<rect x='${x}' y='${y}' width='${COL_W}' height='${height}' rx='8' fill='${C.colBg}' ` +
    `stroke='${C.colBorder}' stroke-width='1'/>` +
    `<g clip-path='url(#${clipId})'>` +
    `<rect x='${x}' y='${y}' width='${COL_W}' height='${HEADER_H}' fill='${C.headerBg}'/>` +
    `</g>` +
    `<line x1='${x}' y1='${y + HEADER_H}' x2='${x + COL_W}' y2='${y + HEADER_H}' stroke='${C.colBorder}' stroke-width='1'/>` +
    `<text x='${x + 7}' y='${y + HEADER_H / 2 + 2.5}' font-size='6.8' font-weight='bold' letter-spacing='0.3' ` +
    `${FONT} fill='${C.headerText}'>${esc(tacticName.toUpperCase())}</text>` +
    `<text x='${x + COL_W - 7}' y='${y + HEADER_H / 2 + 2.5}' font-size='6.8' text-anchor='end' ` +
    `${FONT} fill='${C.faint}'>${techniques.length}</text>` +
    cells.join("");
  return { svg, height };
}

export function buildMatrixSvg(opts: {
  catalog: Catalog;
  state: LayerState;
  theme: HeatTheme;
  title: string;
  sortBy: TechniqueSort;
}): string {
  const { catalog, state, theme, title, sortBy } = opts;
  const gridTop = PAD + TITLE_H;
  const columns: string[] = [];
  let maxColHeight = 0;

  catalog.tactics.forEach((tactic, col) => {
    const x = PAD + col * (COL_W + COL_GAP);
    const rendered = renderColumn(tactic.name, tactic.techniques, x, gridTop, state, theme, sortBy, `col-clip-${col}`);
    columns.push(rendered.svg);
    maxColHeight = Math.max(maxColHeight, rendered.height);
  });

  const width = PAD * 2 + catalog.tactics.length * (COL_W + COL_GAP) - COL_GAP;
  const height = gridTop + maxColHeight + PAD;

  // Heat legend (0 → 100), mirroring the toolbar's gradient swatch. Shifted
  // left of the right margin so the trailing "100" label fits inside it.
  const legendW = 90;
  const legendX = width - PAD - legendW - 22;
  const legendY = PAD + 2;
  const gradientStops = theme.stops
    .map((c, i) => `<stop offset='${(i / (theme.stops.length - 1)) * 100}%' stop-color='rgb(${c.join(",")})'/>`)
    .join("");
  const legend =
    `<defs><linearGradient id='heat-ramp' x1='0' y1='0' x2='1' y2='0'>${gradientStops}</linearGradient></defs>` +
    `<text x='${legendX - 6}' y='${legendY + 8}' font-size='8' text-anchor='end' ${FONT} fill='${C.faint}'>0</text>` +
    `<rect x='${legendX}' y='${legendY}' width='${legendW}' height='10' rx='3' fill='url(#heat-ramp)'/>` +
    `<text x='${legendX + legendW + 6}' y='${legendY + 8}' font-size='8' ${FONT} fill='${C.faint}'>100</text>`;

  return (
    `<svg xmlns='http://www.w3.org/2000/svg' width='${width}' height='${height}' viewBox='0 0 ${width} ${height}'>` +
    `<rect width='${width}' height='${height}' fill='${C.pageBg}'/>` +
    legend +
    `<text x='${PAD}' y='${PAD + 16}' font-size='15' font-weight='bold' ${FONT} fill='${C.title}'>${esc(title)}</text>` +
    columns.join("") +
    `</svg>`
  );
}
