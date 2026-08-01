import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import * as debrief from '../debrief';
import { clearDb } from '../mock-db';
import { list as listReqs } from '../requisitions';
import { seedDb } from '../seed';

beforeEach(() => {
  clearDb();
  if (typeof window !== 'undefined') window.__LATENCY_MS = 0;
  seedDb();
});
afterEach(() => clearDb());

describe('debrief service', () => {
  test('get returns candidate rows for a seeded req', async () => {
    const reqs = await listReqs();
    const first = reqs.items[0];
    if (!first) throw new Error('expected reqs');
    const d = await debrief.get(first.id);
    expect(d.candidates.length).toBeGreaterThan(0);
  });

  test('getInsights returns recommended next steps', async () => {
    const reqs = await listReqs();
    const first = reqs.items[0];
    if (!first) throw new Error('expected reqs');
    const ins = await debrief.getInsights(first.id);
    expect(ins.recommended_next_steps.length).toBeGreaterThan(0);
  });
});
