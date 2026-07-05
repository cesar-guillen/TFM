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
}

/** In-memory editing state, keyed by technique ID for O(1) lookup. */
export type LayerState = Record<string, { score: number; comment?: string }>;

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
