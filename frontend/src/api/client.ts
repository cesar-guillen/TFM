import type { Catalog, Layer } from "../types/attack";

/** Carries the HTTP status so callers can tell a 404 — the job no longer
 * exists server-side, e.g. the backend restarted and lost its in-memory job
 * registry — apart from a transient network failure worth retrying. */
export class HttpError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "HttpError";
    this.status = status;
  }
}

/** Every call goes through here: one place that throws HttpError with the
 * server's message, and one place that percent-encodes path segments. */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init);
  if (!res.ok) {
    throw new HttpError(res.status, `${init?.method ?? "GET"} ${path} failed: ${res.status} ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

function sendJson<T>(method: "POST" | "PUT", path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Path segments come from ids the user can influence (a ?saved= query
 * parameter), so they are always encoded rather than interpolated raw. */
const seg = encodeURIComponent;

export interface IngestStarted {
  report_id: string;
  filename: string;
  status: "parsing";
}

export type IngestStatusValue = "parsing" | "chunking" | "embedding" | "done" | "error" | "cancelled";

/** Statuses at which a job has stopped for good — polling ends here. */
export function isTerminal(status: string): boolean {
  return status === "done" || status === "error" || status === "cancelled";
}

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

export function ingestPdf(file: File, ocrEnabled = true): Promise<IngestStarted> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("ocr", String(ocrEnabled));
  return request<IngestStarted>("/ingest", { method: "POST", body: formData });
}

export function getIngestStatus(reportId: string): Promise<IngestStatus> {
  return request<IngestStatus>(`/ingest/${seg(reportId)}/status`);
}

export type MappingStatusValue =
  | "warming"
  | "retrieving"
  | "mapping"
  | "filtering"
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
 * "off" = no verification, "demote" = keep it at a near-floor score and flag
 * it (rendered as a yellow-outlined cell — see LayerState.flagged), "drop" =
 * remove it outright. */
export type VerifyMode = "off" | "demote" | "drop";

/** Verdict architecture: "menu" judges all candidate techniques of a chunk in
 * one LLM call; "independent" asks one small question per candidate — better
 * recall and reproducible runs, can raise false positives on some reports,
 * ~1.5× slower. */
export type VerdictMode = "menu" | "independent";

/** What kind of document was uploaded — picks the mapping prompt family:
 * "incident" maps what the intruder was observed doing; "pentest" treats the
 * testers as the adversary (first-person narration counts, findings merely
 * identified but not exploited don't). */
export type ReportType = "incident" | "pentest";

export interface MapOptions {
  /** Verification mode for this run. Omit for the server default. */
  verify_mode?: VerifyMode;
  /** Verdict architecture for this run. Omit for the server default. */
  verdict_mode?: VerdictMode;
  /** Report kind for this run's prompts. Omit for the server default. */
  report_type?: ReportType;
}

export function startMapping(
  reportId: string,
  options?: MapOptions,
): Promise<{ report_id: string; status: MappingStatusValue }> {
  return sendJson("POST", `/reports/${seg(reportId)}/map`, options ?? {});
}

/** Ask a running job to stop (no-op if it already finished). The job settles
 * to status "cancelled" at its next safe boundary. */
export async function cancelIngest(reportId: string): Promise<void> {
  await request(`/ingest/${seg(reportId)}/cancel`, { method: "POST" });
}

export async function cancelMapping(reportId: string): Promise<void> {
  await request(`/reports/${seg(reportId)}/map/cancel`, { method: "POST" });
}

export function getMappingStatus(reportId: string): Promise<MappingStatus> {
  return request<MappingStatus>(`/reports/${seg(reportId)}/map/status`);
}

export function getAttackCatalog(): Promise<Catalog> {
  return request<Catalog>("/attack/catalog");
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

export function getMatrixHistory(): Promise<SavedMatrixSummary[]> {
  return request<SavedMatrixSummary[]>("/matrix/history");
}

export function getSavedMatrix(id: string): Promise<SavedMatrix> {
  return request<SavedMatrix>(`/matrix/history/${seg(id)}`);
}

export function createSavedMatrix(name: string, layer: Layer): Promise<SavedMatrix> {
  return sendJson<SavedMatrix>("POST", "/matrix/history", { name, layer });
}

export function updateSavedMatrix(id: string, name: string, layer: Layer): Promise<SavedMatrix> {
  return sendJson<SavedMatrix>("PUT", `/matrix/history/${seg(id)}`, { name, layer });
}

export async function deleteSavedMatrix(id: string): Promise<void> {
  await request(`/matrix/history/${seg(id)}`, { method: "DELETE" });
}

/** LLM warm-up state: device is null until it's knowable (nothing loaded in
 * Ollama yet), so the UI can keep GPU wording away from CPU-only machines. */
export interface WarmupStatus {
  status: "unknown" | "loading" | "ready" | "unavailable";
  device: "gpu" | "cpu" | null;
  model: string;
}

export function getWarmupStatus(): Promise<WarmupStatus> {
  return request<WarmupStatus>("/warmup");
}
