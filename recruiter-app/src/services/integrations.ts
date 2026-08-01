import type { ConnectResult, Integration, IntegrationProvider } from '@/domain';
import { isV2ApiEnabled } from '@/lib/env';
import { emit } from './events';
import { simulate } from './latency';
import { generateId, getDb, nowIso, persist } from './mock-db';
import { notImplementedInV2, ServiceError } from './service-error';

export async function list(): Promise<Integration[]> {
  if (isV2ApiEnabled()) throw notImplementedInV2('integrations.list');
  await simulate();
  return structuredClone(getDb().integrations);
}

export async function connect(provider: IntegrationProvider): Promise<ConnectResult> {
  if (isV2ApiEnabled()) throw notImplementedInV2('integrations.connect');
  await simulate();
  const db = getDb();
  const item = db.integrations.find((i) => i.provider === provider);
  if (!item) throw new ServiceError('not_found', `Integration ${provider} not found`);
  item.status = 'connected';
  item.connected_at = nowIso();
  item.last_synced_at = nowIso();
  db.activity.unshift({
    id: generateId('act'),
    type: 'integration:connected',
    title: 'Integration connected',
    description: `${item.label} is now connected.`,
    actor_name: db.profile.name,
    requisition_id: null,
    candidate_id: null,
    created_at: nowIso(),
  });
  persist();
  emit('integration:updated', item);
  emit('activity:created');
  return { provider, auth_url: `#oauth/${provider}` };
}

export async function disconnect(provider: IntegrationProvider): Promise<Integration> {
  if (isV2ApiEnabled()) throw notImplementedInV2('integrations.disconnect');
  await simulate();
  const db = getDb();
  const item = db.integrations.find((i) => i.provider === provider);
  if (!item) throw new ServiceError('not_found', `Integration ${provider} not found`);
  item.status = 'available';
  item.connected_at = null;
  item.last_synced_at = null;
  db.activity.unshift({
    id: generateId('act'),
    type: 'integration:disconnected',
    title: 'Integration disconnected',
    description: `${item.label} was disconnected.`,
    actor_name: db.profile.name,
    requisition_id: null,
    candidate_id: null,
    created_at: nowIso(),
  });
  persist();
  emit('integration:updated', item);
  emit('activity:created');
  return structuredClone(item);
}

export async function getStatus(provider: IntegrationProvider): Promise<Integration> {
  if (isV2ApiEnabled()) throw notImplementedInV2('integrations.getStatus');
  await simulate();
  const item = getDb().integrations.find((i) => i.provider === provider);
  if (!item) throw new ServiceError('not_found', `Integration ${provider} not found`);
  return structuredClone(item);
}
