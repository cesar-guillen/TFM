/** "4m 12s" / "58s" / "<1s" / "1h 03m" — for pipeline-step durations. */
export function formatDuration(seconds: number): string {
  const total = Math.round(seconds);
  if (total < 1) return "<1s";
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes}m ${String(total % 60).padStart(2, "0")}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${String(minutes % 60).padStart(2, "0")}m`;
}
