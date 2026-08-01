import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import type { IntegrationProvider } from '@/domain';
import * as integrations from '../integrations';
import { clearDb } from '../mock-db';
import { seedDb } from '../seed';

beforeEach(() => {
  clearDb();
  if (typeof window !== 'undefined') window.__LATENCY_MS = 0;
  seedDb();
});
afterEach(() => clearDb());

describe('integrations service', () => {
  test('connect flips status to connected', async () => {
    await integrations.connect('google_calendar');
    const status = await integrations.getStatus('google_calendar');
    expect(status.status).toBe('connected');
    expect(status.connected_at).toBeTruthy();
  });

  test('disconnect flips back to available', async () => {
    await integrations.disconnect('slack');
    const status = await integrations.getStatus('slack');
    expect(status.status).toBe('available');
  });

  test('unknown provider throws not_found', async () => {
    await expect(integrations.getStatus('nope' as IntegrationProvider)).rejects.toThrow(
      /not found/,
    );
  });
});
