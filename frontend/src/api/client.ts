import type { Catalog, Layer } from "../types/attack";

export interface IngestStarted {
  report_id: string;
  filename: string;
  status: "parsing";
}

export type IngestStatusValue = "parsing" | "chunking" | "embedding" | "done" | "error";

export interface IngestStatus {
  report_id: string;
  filename: string;
  status: IngestStatusValue;
  chunk_count: number;
  chunks_embedded: number;
  markdown: string | null;
  error: string | null;
}

export async function ingestPdf(file: File): Promise<IngestStarted> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch("/api/ingest", { method: "POST", body: formData });
  if (!res.ok) {
    throw new Error(`Ingest failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

export async function getIngestStatus(reportId: string): Promise<IngestStatus> {
  const res = await fetch(`/api/ingest/${reportId}/status`);
  if (!res.ok) {
    throw new Error(`Fetching ingest status failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

export type MappingStatusValue = "warming" | "retrieving" | "mapping" | "aggregating" | "done" | "error";

export interface MappingStatus {
  report_id: string;
  status: MappingStatusValue;
  chunk_count: number;
  chunks_mapped: number;
  layer: Layer | null;
  error: string | null;
}

export async function startMapping(reportId: string): Promise<{ report_id: string; status: MappingStatusValue }> {
  const res = await fetch(`/api/reports/${reportId}/map`, { method: "POST" });
  if (!res.ok) {
    throw new Error(`Starting mapping failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

export async function getMappingStatus(reportId: string): Promise<MappingStatus> {
  const res = await fetch(`/api/reports/${reportId}/map/status`);
  if (!res.ok) {
    throw new Error(`Fetching mapping status failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

export async function getAttackCatalog(): Promise<Catalog> {
  const res = await fetch("/api/attack/catalog");
  if (!res.ok) {
    throw new Error(`Fetching ATT&CK catalog failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

export async function getMatrixLayer(): Promise<Layer> {
  const res = await fetch("/api/matrix");
  if (!res.ok) {
    throw new Error(`Fetching matrix layer failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

/** A saved matrix in the backend's on-disk library: every mapping run lands
 * here automatically, and manual saves from the editor go here too.
 * `filename` is the source report for generated entries, null for matrices
 * saved by hand. */
export interface SavedMatrixSummary {
  id: string;
  name: string;
  filename: string | null;
  created_at: string;
  updated_at: string | null;
  technique_count: number;
}

export interface SavedMatrix extends SavedMatrixSummary {
  layer: Layer;
}

export async function getMatrixHistory(): Promise<SavedMatrixSummary[]> {
  const res = await fetch("/api/matrix/history");
  if (!res.ok) {
    throw new Error(`Fetching matrix history failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

export async function getSavedMatrix(id: string): Promise<SavedMatrix> {
  const res = await fetch(`/api/matrix/history/${id}`);
  if (!res.ok) {
    throw new Error(`Fetching saved matrix failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

export async function createSavedMatrix(name: string, layer: Layer): Promise<SavedMatrix> {
  const res = await fetch("/api/matrix/history", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, layer }),
  });
  if (!res.ok) {
    throw new Error(`Saving matrix failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

export async function updateSavedMatrix(id: string, name: string, layer: Layer): Promise<SavedMatrix> {
  const res = await fetch(`/api/matrix/history/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, layer }),
  });
  if (!res.ok) {
    throw new Error(`Saving matrix failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

export async function deleteSavedMatrix(id: string): Promise<void> {
  const res = await fetch(`/api/matrix/history/${id}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error(`Deleting saved matrix failed: ${res.status} ${await res.text()}`);
  }
}

/** LLM warm-up state: device is null until it's knowable (nothing loaded in
 * Ollama yet), so the UI can keep GPU wording away from CPU-only machines. */
export interface WarmupStatus {
  status: "unknown" | "loading" | "ready" | "unavailable";
  device: "gpu" | "cpu" | null;
  model: string;
}

export async function getWarmupStatus(): Promise<WarmupStatus> {
  const res = await fetch("/api/warmup");
  if (!res.ok) {
    throw new Error(`Fetching warmup status failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}
