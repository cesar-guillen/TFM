/** Persists the currently-processing report across tab reloads / navigation.
 *
 * The backend keeps ingest and mapping jobs in in-memory registries keyed by
 * report_id for the life of the backend process, and its status endpoints
 * return the full job state (including the live partial layer). So all the
 * frontend has to remember to "go back to the report being processed" after a
 * reload is the active report_id — this stores it in localStorage, and the
 * dashboard rehydrates its run view from it on mount and resumes polling.
 *
 * It's cleared when the run reaches `done` (the finished matrix is in the
 * library from then on) and when the user cancels. Going to the library with
 * "← All matrices" does NOT clear it — the run keeps polling in the background
 * and is offered back via a resume banner — and an errored run is kept too, so
 * a reload still lands on the retry view. */
export interface ActiveRun {
  reportId: string;
  filename: string;
  /** Whether the mapping stage has already been started for this report.
   * Distinguishes "closed during ingest" (mapping still needs auto-starting on
   * return) from "closed during mapping" (just resume polling the map job). */
  mappingStarted: boolean;
}

const KEY = "tfm-active-run";

export function loadActiveRun(): ActiveRun | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<ActiveRun>;
    if (typeof parsed?.reportId === "string" && typeof parsed?.filename === "string") {
      return {
        reportId: parsed.reportId,
        filename: parsed.filename,
        mappingStarted: Boolean(parsed.mappingStarted),
      };
    }
  } catch {
    // Malformed JSON or storage unavailable (private mode) — no session to
    // restore; fall through to the library like a fresh visit.
  }
  return null;
}

export function saveActiveRun(run: ActiveRun): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(run));
  } catch {
    // Storage unavailable / quota — session persistence just won't survive a
    // reload; the run itself keeps working. Not fatal.
  }
}

export function clearActiveRun(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    // ignore
  }
}
