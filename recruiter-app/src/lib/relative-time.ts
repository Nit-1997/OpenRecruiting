/**
 * Render an ISO timestamp as a short relative label ("2m ago", "3h ago",
 * "5d ago"). Clamps to a minimum of "1m ago" so a just-now timestamp never
 * reads "0m ago". Shared by the debrief surfaces (packet toolbar, role tab,
 * insight summary) so the relative-time formatting stays single-sourced.
 */
export function relativeTimeFrom(iso: string): string {
  const then = new Date(iso).getTime();
  const diffMin = Math.max(1, Math.round((Date.now() - then) / 60000));
  if (diffMin < 60) return `${diffMin}m ago`;
  const h = Math.round(diffMin / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  return `${d}d ago`;
}
