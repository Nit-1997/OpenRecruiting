import { RAIL_VIEW_REGISTRY } from '@/components/rail-views';

export default function IntegrationsPage() {
  const View = RAIL_VIEW_REGISTRY.integrations.View;
  return <View id="integrations-view" />;
}
