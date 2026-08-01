import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import * as activity from '../activity';
import { clearDb } from '../mock-db';
import { create as createReq } from '../requisitions';
import { seedDb } from '../seed';

beforeEach(() => {
  clearDb();
  if (typeof window !== 'undefined') window.__LATENCY_MS = 0;
  seedDb();
});
afterEach(() => clearDb());

describe('activity service', () => {
  test('list returns seeded events', async () => {
    const rows = await activity.list();
    expect(rows.length).toBeGreaterThan(0);
  });

  test('new role prepends an activity row', async () => {
    const before = await activity.list();
    await createReq({
      role_title: 'Fresh',
      role_location: '',
      department: 'Product',
      created_by: 'user_1',
      created_by_name: 'Nitin',
    });
    const after = await activity.list();
    expect(after.length).toBe(before.length + 1);
    expect(after[0]?.type).toBe('role:created');
  });
});
