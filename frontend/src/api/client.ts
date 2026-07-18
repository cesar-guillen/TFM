import type { Catalog, Layer } from "../types/attack";

export interface IngestStarted {
  report_id: string;
  filename: string;
  status: "parsing";
}

export type IngestStatusValue = "parsing" | "chunking" | "embedding" | "done" | "error" | "cancelled";

export interface IngestStatus {
  report_id: string;
  filename: string;
  status: IngestStatusValue;
  chunk_count: number;
  chunks_embedded: number;
  markdown: string | null;
  error: string | null;
  /** Per-step durations (keyed by status name); the running step is included
   * at its elapsed-so-far, completed steps are frozen. */
  step_seconds: Record<string, number>;
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

export type MappingStatusValue =
  | "warming"
  | "retrieving"
  | "mapping"
  | "aggregating"
  | "done"
  | "error"
  | "cancelled";

export interface MappingStatus {
  report_id: string;
  status: MappingStatusValue;
  chunk_count: number;
  chunks_mapped: number;
  layer: Layer | null;
  error: string | null;
  /** Ticks while the job runs; frozen at the final duration once terminal. */
  elapsed_seconds: number;
  /** Per-phase durations (keyed by status name); the running phase is
   * included at its elapsed-so-far, completed phases are frozen. */
  step_seconds: Record<string, number>;
}

/** What the verification pass does with a mapping it can't confirm:
 * "off" = no verification, "demote" = keep it at a near-floor score with a
 * marked comment, "drop" = remove it. */
export type VerifyMode = "off" | "demote" | "drop";

export interface MapOptions {
  /** Verification mode for this run. Omit for the server default. */
  verify_mode?: VerifyMode;
}

export async function startMapping(
  reportId: string,
  options?: MapOptions,
): Promise<{ report_id: string; status: MappingStatusValue }> {
  const res = await fetch(`/api/reports/${reportId}/map`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(options ?? {}),
  });
  if (!res.ok) {
    throw new Error(`Starting mapping failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

/** Ask a running job to stop (no-op if it already finished). The job settles
 * to status "cancelled" at its next safe boundary. */
export async function cancelIngest(reportId: string): Promise<void> {
  const res = await fetch(`/api/ingest/${reportId}/cancel`, { method: "POST" });
  if (!res.ok) {
    throw new Error(`Cancelling ingest failed: ${res.status} ${await res.text()}`);
  }
}

export async function cancelMapping(reportId: string): Promise<void> {
  const res = await fetch(`/api/reports/${reportId}/map/cancel`, { method: "POST" });
  if (!res.ok) {
    throw new Error(`Cancelling mapping failed: ${res.status} ${await res.text()}`);
  }
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
  /** How long the mapping run took; null for hand-saved matrices (and
   * entries saved before this field existed). */
  duration_seconds: number | null;
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
