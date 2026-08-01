export const RAIL_VIEW_IDS = ['roles', 'integrations'] as const;
export type RailViewId = (typeof RAIL_VIEW_IDS)[number];

export const RAIL_VIEW_LABELS: Record<RailViewId, string> = {
  roles: 'Roles',
  integrations: 'Integrations',
};
