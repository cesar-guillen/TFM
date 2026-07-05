import type { Catalog, Layer } from "../types/attack";

export async function ingestPdf(file: File): Promise<{ filename: string; markdown: string }> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch("/api/ingest", { method: "POST", body: formData });
  if (!res.ok) {
    throw new Error(`Ingest failed: ${res.status} ${await res.text()}`);
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
