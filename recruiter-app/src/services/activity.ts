import type { ActivityEvent } from '@/domain';
import { isV2ApiEnabled } from '@/lib/env';
import { simulate } from './latency';
import { getDb } from './mock-db';
import { notImplementedInV2 } from './service-error';

export async function list(limit = 20): Promise<ActivityEvent[]> {
  if (isV2ApiEnabled()) throw notImplementedInV2('activity.list');
  await simulate();
  return structuredClone(getDb().activity.slice(0, limit));
}
