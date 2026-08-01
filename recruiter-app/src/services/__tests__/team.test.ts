// team.ts is a v2-only service: every export forwards to `v2Client` and maps
// the wire shape onto the domain types. These tests mock `@/lib/v2-client`
// (same idiom as v2-wiring.test.ts), force the v2 flag on, then assert the
// request method/path/body plus the unwrapped/mapped return value. The old
// mock-db contract these tests used to exercise (client-side email validation,
// owner-removal guard) no longer lives in the FE service — those are backend
// concerns reached over `/api/v2/team`.
process.env.NEXT_PUBLIC_API_URL = 'http://test.invalid';

import { afterAll, afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';

beforeEach(() => {
  process.env.NEXT_PUBLIC_V2_API = 'true';
});

afterAll(() => {
  process.env.NEXT_PUBLIC_V2_API = 'false';
  delete process.env.NEXT_PUBLIC_API_URL;
});

type Call = { method: string; path: string; body?: unknown };
const calls: Call[] = [];
let nextResponse: unknown = null;

function resetMock() {
  calls.length = 0;
  nextResponse = null;
}

mock.module('@/lib/v2-client', () => {
  // Spread the REAL module: mock.module is process-wide last-writer-wins, so a
  // partial replacement would strip resolveV2Token/runV2UnauthorizedHandler for
  // any concurrently-scheduled test file and break cross-file `instanceof
  // V2ApiError`. Only v2Client is stubbed; everything else stays real.
  const actual = require('@/lib/v2-client');
  function record<T>(method: string, path: string, body?: unknown): Promise<T> {
    const call: Call = { method, path };
    if (body !== undefined) call.body = body;
    calls.push(call);
    return Promise.resolve(nextResponse as T);
  }
  return {
    ...actual,
    v2Client: {
      get: (path: string) => record('GET', path),
      post: (path: string, body?: unknown) => record('POST', path, body),
      put: (path: string, body?: unknown) => record('PUT', path, body),
      delete: (path: string) => record('DELETE', path),
    },
    setV2TokenGetter: () => {},
  };
});

// Imported after the mock is registered so the service binds to the stub.
import * as team from '../team';

beforeEach(() => resetMock());
afterEach(() => resetMock());

describe('team service', () => {
  test('get fetches /api/v2/team and maps to TeamOverview', async () => {
    nextResponse = {
      organization_id: 'org_1',
      organization_name: 'OpenRecruiting',
      members: [
        {
          id: 'm1',
          user_id: 'user_1',
          name: 'Nitin',
          email: 'founder@example.com',
          role: 'owner',
          avatar_initials: 'N',
          avatar_color: '#EEE8DD',
          joined_at: '2026-01-01T00:00:00Z',
          last_active_at: null,
        },
      ],
      pending_invites: [],
      seat_usage: { used: 1, total: 10 },
    };
    const overview = await team.get();
    expect(calls).toHaveLength(1);
    const call = calls[0];
    if (!call) throw new Error('expected a call');
    expect(call.method).toBe('GET');
    expect(call.path).toBe('/api/v2/team');
    expect(overview.organization_name).toBe('OpenRecruiting');
    expect(overview.members[0]?.role).toBe('owner');
    expect(overview.seat_usage).toEqual({ used: 1, total: 10 });
  });

  test('invite POSTs {email, role} to /api/v2/team/invite and maps the result', async () => {
    nextResponse = {
      id: 'inv_1',
      email: 'priya@ex.com',
      role: 'recruiter',
      invited_by_id: 'user_1',
      invited_by_name: 'Nitin',
      created_at: '2026-01-01T00:00:00Z',
      expires_at: '2026-01-08T00:00:00Z',
      status: 'pending',
    };
    const inv = await team.invite('priya@ex.com', 'recruiter');
    expect(calls).toHaveLength(1);
    const call = calls[0];
    if (!call) throw new Error('expected a call');
    expect(call.method).toBe('POST');
    expect(call.path).toBe('/api/v2/team/invite');
    expect(call.body).toEqual({ email: 'priya@ex.com', role: 'recruiter' });
    expect(inv.id).toBe('inv_1');
    expect(inv.email).toBe('priya@ex.com');
    expect(inv.status).toBe('pending');
  });

  test('invite defaults null invited_by fields to empty strings', async () => {
    nextResponse = {
      id: 'inv_2',
      email: 'sam@ex.com',
      role: 'viewer',
      invited_by_id: null,
      invited_by_name: null,
      created_at: '2026-01-01T00:00:00Z',
      expires_at: '2026-01-08T00:00:00Z',
      status: 'pending',
    };
    const inv = await team.invite('sam@ex.com', 'viewer');
    expect(inv.invited_by_id).toBe('');
    expect(inv.invited_by_name).toBe('');
  });

  test('remove DELETEs /api/v2/team/members/{id}', async () => {
    nextResponse = null;
    await team.remove('m1');
    expect(calls).toHaveLength(1);
    const call = calls[0];
    if (!call) throw new Error('expected a call');
    expect(call.method).toBe('DELETE');
    expect(call.path).toBe('/api/v2/team/members/m1');
  });

  test('cancelInvite DELETEs /api/v2/team/invites/{id}', async () => {
    nextResponse = null;
    await team.cancelInvite('inv_1');
    expect(calls).toHaveLength(1);
    const call = calls[0];
    if (!call) throw new Error('expected a call');
    expect(call.method).toBe('DELETE');
    expect(call.path).toBe('/api/v2/team/invites/inv_1');
  });
});
