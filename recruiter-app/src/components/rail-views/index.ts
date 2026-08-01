import type { FC } from 'react';
import type { RailViewId } from '@/types';
import { IntegrationsView } from './integrations/view';
import { RolesView } from './roles/view';

export interface RailViewModule {
  id: RailViewId;
  View: FC<{ id: string }>;
}

export const RAIL_VIEW_REGISTRY: Record<RailViewId, RailViewModule> = {
  roles: { id: 'roles', View: RolesView },
  integrations: { id: 'integrations', View: IntegrationsView },
};
