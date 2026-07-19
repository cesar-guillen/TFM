export interface TechniqueSummary {
  id: string;
  name: string;
  url: string;
}

export interface CatalogTechnique extends TechniqueSummary {
  subtechniques: TechniqueSummary[];
}

export interface CatalogTactic {
  id: string;
  name: string;
  techniques: CatalogTechnique[];
}

export interface Catalog {
  tactics: CatalogTactic[];
}

export interface LayerTechniqueEntry {
  techniqueID: string;
  score?: number;
  comment?: string;
  enabled?: boolean;
}

export interface Layer {
  name: string;
  versions: { attack: string; navigator: string; layer: string };
  domain: string;
  description: string;
  techniques: LayerTechniqueEntry[];
  /** Backend history-entry id stamped into saved layers (see
   * app/mapping/history.py) — tells the editor which entry a layer belongs
   * to, so re-saving updates it instead of creating a duplicate. */
  tfm_saved_id?: string;
}

/** In-memory editing state, keyed by technique ID for O(1) lookup. */
export type LayerState = Record<string, { score: number; comment?: string }>;

/** Vertical ordering of techniques inside each tactic column. */
export type TechniqueSort = "default" | "score" | "name";

/** Sort key for a parent row: the average score of every marked entry in its
 * group (its own, if scored, plus each marked sub-technique) — so a parent
 * with several strong subs outranks one carried by a single lucky sub, and a
 * parent highlighted only via a sub still ranks by that evidence. Unmarked
 * groups sink below any marked one. */
function groupScore(tech: CatalogTechnique, layer: LayerState): number {
  let sum = 0;
  let count = 0;
  const own = layer[tech.id]?.score;
  if (own !== undefined) {
    sum += own;
    count += 1;
  }
  for (const sub of tech.subtechniques) {
    const score = layer[sub.id]?.score;
    if (score !== undefined) {
      sum += score;
      count += 1;
    }
  }
  return count === 0 ? -1 : sum / count;
}

export function sortTechniques(
  list: CatalogTechnique[],
  layer: LayerState,
  sortBy: TechniqueSort
): CatalogTechnique[] {
  if (sortBy === "default") return list;
  const copy = [...list];
  if (sortBy === "name") copy.sort((a, b) => a.name.localeCompare(b.name));
  else copy.sort((a, b) => groupScore(b, layer) - groupScore(a, layer) || a.name.localeCompare(b.name));
  return copy;
}

export function sortSubtechniques(
  list: TechniqueSummary[],
  layer: LayerState,
  sortBy: TechniqueSort
): TechniqueSummary[] {
  if (sortBy === "default") return list;
  const copy = [...list];
  if (sortBy === "name") copy.sort((a, b) => a.name.localeCompare(b.name));
  else
    copy.sort(
      (a, b) => (layer[b.id]?.score ?? -1) - (layer[a.id]?.score ?? -1) || a.name.localeCompare(b.name)
    );
  return copy;
}

export function layerToState(layer: Layer): LayerState {
  const state: LayerState = {};
  for (const entry of layer.techniques) {
    if (entry.enabled === false) continue;
    state[entry.techniqueID] = { score: entry.score ?? 100, comment: entry.comment };
  }
  return state;
}

export function stateToLayer(state: LayerState, base: Layer): Layer {
  return {
    ...base,
    techniques: Object.entries(state).map(([techniqueID, { score, comment }]) => ({
      techniqueID,
      score,
      comment: comment || undefined,
      enabled: true,
    })),
  };
}
