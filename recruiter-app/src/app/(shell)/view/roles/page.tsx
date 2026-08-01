import { RAIL_VIEW_REGISTRY } from '@/components/rail-views';

export default function RolesPage() {
  const View = RAIL_VIEW_REGISTRY.roles.View;
  return <View id="roles-view" />;
}
