import type { SubAgentId } from '@/types';

/**
 * Pre-launch visibility gates — single source of truth.
 *
 * Several agents are built but not production-ready yet. For launch they're
 * shown in the hub (so it looks complete) as disabled "Coming soon" tiles/tabs,
 * but are non-clickable and their routes bounce to home. The nav tabs, home hub
 * cards, suggestion cards, composer chips, and the /brain + /debrief route guards
 * all read from here.
 *
 * To release a feature later: remove its id from LAUNCH_COMING_SOON_SUB_AGENTS.
 * No other code changes are needed — flows, registry, and routes stay intact.
 */

/** Built but not ready: shown as disabled "Coming soon" tiles/tabs (non-clickable). */
export const LAUNCH_COMING_SOON_SUB_AGENTS: ReadonlySet<SubAgentId> = new Set<SubAgentId>([
  'brain', // labelled "Insights Agent"
]);

export function isSubAgentComingSoon(id: SubAgentId): boolean {
  return LAUNCH_COMING_SOON_SUB_AGENTS.has(id);
}

/** Fully hidden — no hub surface at all. (sourcing has no hub card; /sourcing already bounces home.) */
export const LAUNCH_HIDDEN_SUB_AGENTS: ReadonlySet<SubAgentId> = new Set<SubAgentId>(['sourcing']);

export function isSubAgentHidden(id: SubAgentId): boolean {
  return LAUNCH_HIDDEN_SUB_AGENTS.has(id);
}

/** Not navigable (hidden OR coming-soon). Used by route guards + composer chips,
 *  which would otherwise bounce to home on click. */
export function isSubAgentLocked(id: SubAgentId): boolean {
  return isSubAgentHidden(id) || isSubAgentComingSoon(id);
}

/** Home hub "Everything looks good" status pill — kept hidden: its placeholder
 *  copy ("3 debriefs ready …") contradicts the Coming-soon debrief state. */
export const LAUNCH_HIDE_HOME_STATUS_WIDGET = true;

/** "Show earlier" chat pill — live: sessions persist to localStorage and every
 *  page load archives the live conversation, so the pill restores REAL prior
 *  turns (fixture seeds remain only as the mock-mode demo fallback). */
export const LAUNCH_HIDE_SHOW_EARLIER = false;
