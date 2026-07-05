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

export type MappingStatusValue = "retrieving" | "mapping" | "aggregating" | "done" | "error";

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
