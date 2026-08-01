import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';

let userFixture: { id: string } | null = null;
mock.module('@/lib/supabase-server', () => ({
  getRecruiterUserFromRequest: async () => userFixture,
}));

import { GET } from './route';

const originalFetch = globalThis.fetch;

describe('GET /api/deepgram — recruiter session branch', () => {
  beforeEach(() => {
    process.env.DEEPGRAM_API_KEY = 'test-master-key';
    process.env.DEEPGRAM_PROJECT_ID = 'test-project';
    userFixture = null;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  test('mints a key for a valid recruiter session (no feedback header)', async () => {
    userFixture = { id: 'user-123' };
    globalThis.fetch = mock(
      async () => new Response(JSON.stringify({ key: 'dg-ephemeral' }), { status: 200 }),
    ) as unknown as typeof fetch;
    const req = new Request('http://localhost/api/deepgram');
    const res = await GET(req as unknown as Parameters<typeof GET>[0]);
    expect(res.status).toBe(200);
    expect((await res.json()).apiKey).toBe('dg-ephemeral');
  });

  test('401 when there is no recruiter session and no feedback header', async () => {
    userFixture = null;
    const req = new Request('http://localhost/api/deepgram');
    const res = await GET(req as unknown as Parameters<typeof GET>[0]);
    expect(res.status).toBe(401);
  });
});
