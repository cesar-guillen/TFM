import { readableTextColor, scoreToColor, type HeatTheme } from "../theme/heatThemes";
import {
  sortSubtechniques,
  sortTechniques,
  type Catalog,
  type LayerState,
  type TechniqueSort,
} from "../types/attack";

/** Standalone SVG render of the matrix, for export (thesis figures, reports).
 * Light, print-friendly styling independent of the app theme; scored cells
 * use the active heat theme's ramp. Flagged sub-techniques are always shown
 * (indented under their parent) regardless of on-screen expansion state. */

const COL_W = 170;
const COL_GAP = 8;
const CELL_H = 26;
const CELL_GAP = 3;
const HEADER_H = 34;
const PAD = 20;
const TITLE_H = 44;
const SUB_INDENT = 14;
const FONT = "font-family='Helvetica, Arial, sans-serif'";
// ~5.3px per character at font-size 9.5 — used to truncate labels to the cell.
const CHAR_W = 5.3;

function esc(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function truncate(text: string, maxPx: number): string {
  const maxChars = Math.floor(maxPx / CHAR_W);
  return text.length <= maxChars ? text : text.slice(0, Math.max(0, maxChars - 1)) + "…";
}

function cell(
  x: number,
  y: number,
  width: number,
  label: string,
  entry: { score: number } | undefined,
  theme: HeatTheme
): string {
  const fill = entry ? scoreToColor(entry.score, theme) : "#f1f2f5";
  const text = entry ? readableTextColor(entry.score, theme) : "#3a3f4c";
  return (
    `<rect x='${x}' y='${y}' width='${width}' height='${CELL_H}' rx='3' fill='${fill}' stroke='#d4d7de' stroke-width='0.5'/>` +
    `<text x='${x + 5}' y='${y + CELL_H / 2 + 3.5}' font-size='9.5' ${FONT} fill='${text}'>${esc(
      truncate(label, width - 10)
    )}</text>`
  );
}

export function buildMatrixSvg(opts: {
  catalog: Catalog;
  state: LayerState;
  theme: HeatTheme;
  title: string;
  sortBy: TechniqueSort;
}): string {
  const { catalog, state, theme, title, sortBy } = opts;
  const columns: string[] = [];
  let maxRows = 0;

  catalog.tactics.forEach((tactic, col) => {
    const x = PAD + col * (COL_W + COL_GAP);
    const parts: string[] = [
      `<rect x='${x}' y='${PAD + TITLE_H}' width='${COL_W}' height='${HEADER_H}' rx='3' fill='#2a3040'/>`,
      `<text x='${x + COL_W / 2}' y='${PAD + TITLE_H + HEADER_H / 2 + 3.5}' font-size='10.5' font-weight='bold' ` +
        `${FONT} fill='#ffffff' text-anchor='middle'>${esc(truncate(tactic.name, COL_W - 10))}</text>`,
    ];

    let row = 0;
    for (const tech of sortTechniques(tactic.techniques, state, sortBy)) {
      const y = PAD + TITLE_H + HEADER_H + CELL_GAP + row * (CELL_H + CELL_GAP);
      parts.push(cell(x, y, COL_W, `${tech.id} ${tech.name}`, state[tech.id], theme));
      row += 1;
      const flaggedSubs = sortSubtechniques(
        tech.subtechniques.filter((s) => state[s.id]),
        state,
        sortBy
      );
      for (const sub of flaggedSubs) {
        const subY = PAD + TITLE_H + HEADER_H + CELL_GAP + row * (CELL_H + CELL_GAP);
        parts.push(cell(x + SUB_INDENT, subY, COL_W - SUB_INDENT, `${sub.id} ${sub.name}`, state[sub.id], theme));
        row += 1;
      }
    }
    maxRows = Math.max(maxRows, row);
    columns.push(parts.join(""));
  });

  const width = PAD * 2 + catalog.tactics.length * (COL_W + COL_GAP) - COL_GAP;
  const height = PAD * 2 + TITLE_H + HEADER_H + CELL_GAP + maxRows * (CELL_H + CELL_GAP);

  return (
    `<svg xmlns='http://www.w3.org/2000/svg' width='${width}' height='${height}' viewBox='0 0 ${width} ${height}'>` +
    `<rect width='${width}' height='${height}' fill='#ffffff'/>` +
    `<text x='${PAD}' y='${PAD + 20}' font-size='17' font-weight='bold' ${FONT} fill='#171a21'>${esc(title)}</text>` +
    columns.join("") +
    `</svg>`
  );
}
