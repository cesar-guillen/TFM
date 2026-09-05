import { readStored, removeStored, writeStored } from "./storage";

/** The report currently being processed, remembered across tab reloads and
 * navigation.
 *
 * Backend jobs live in memory keyed by report_id and their status endpoints
 * return the full state (including the live partial layer), so all the
 * frontend has to remember is the id: the dashboard rehydrates its run view
 * from it on mount and resumes polling.
 *
 * Cleared when the run reaches "done" (the finished matrix is in the library
 * from then on) and on cancel. Going back to the library does NOT clear it —
 * the run keeps polling and is offered back via a resume banner — and an
 * errored run is kept too, so a reload lands on the retry view.
 */
export interface ActiveRun {
  reportId: string;
  filename: string;
  /** Whether mapping has already been started for this report. Distinguishes
   * "closed during ingest" (mapping still needs auto-starting on return) from
   * "closed during mapping" (just resume polling the map job). */
  mappingStarted: boolean;
}

const KEY = "tfm-active-run";

export function loadActiveRun(): ActiveRun | null {
  const raw = readStored(KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<ActiveRun>;
    if (typeof parsed?.reportId !== "string" || typeof parsed?.filename !== "string") return null;
    return {
      reportId: parsed.reportId,
      filename: parsed.filename,
      mappingStarted: Boolean(parsed.mappingStarted),
    };
  } catch {
    return null; // malformed entry — start as if there were no session
  }
}

export function saveActiveRun(run: ActiveRun): void {
  writeStored(KEY, JSON.stringify(run));
}

export function clearActiveRun(): void {
  removeStored(KEY);
}
