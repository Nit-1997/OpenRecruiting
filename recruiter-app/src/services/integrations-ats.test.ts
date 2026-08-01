import { afterEach, describe, expect, mock, test } from 'bun:test';
import {
  applyAtsUpdate,
  completeAtsConnection,
  disconnectAts,
  dismissAtsUpdate,
  getAtsSessionToken,
  getAtsStatus,
  getRequisitionAtsSync,
  runAtsImport,
} from './integrations-ats';

const originalFetch = globalThis.fetch;

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('integrations-ats service', () => {
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  test('getAtsSessionToken POSTs /session and unwraps token', async () => {
    const fetchMock = mock(async () => jsonResponse({ token: 'sess-tok' }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    expect(await getAtsSessionToken()).toBe('sess-tok');
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(url)).toContain('/api/v2/integrations/ats/session');
    expect(init.method).toBe('POST');
  });

  test('completeAtsConnection POSTs the verbatim integrationDetails', async () => {
    const fetchMock = mock(async () =>
      jsonResponse({
        connected: true,
        provider: 'workable',
        status: 'active',
        connected_at: '2026-06-11T00:00:00Z',
        connected_by_name: 'Rae',
      }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const details = {
      integrationId: 'int-1',
      appId: 'workable',
      categoryId: 'ATS',
      originOrgId: 'org-1',
      success: true,
    };
    const status = await completeAtsConnection(details);
    expect(status.connected).toBe(true);
    expect(status.provider).toBe('workable');

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(url)).toContain('/api/v2/integrations/ats/connections');
    expect(JSON.parse(String(init.body))).toEqual(details);
  });

  test('getAtsStatus GETs /status', async () => {
    const fetchMock = mock(async () =>
      jsonResponse({
        connected: false,
        provider: null,
        status: null,
        connected_at: null,
        connected_by_name: null,
      }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const status = await getAtsStatus();
    expect(status.connected).toBe(false);
    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(String(url)).toContain('/api/v2/integrations/ats/status');
  });

  test('disconnectAts DELETEs /connection', async () => {
    const fetchMock = mock(async () => jsonResponse({ disconnected: true }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await disconnectAts();
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(url)).toContain('/api/v2/integrations/ats/connection');
    expect(init.method).toBe('DELETE');
  });

  test('runAtsImport POSTs /import with include_closed', async () => {
    const fetchMock = mock(async () =>
      jsonResponse({
        created: 2,
        updated: 0,
        flagged: 0,
        skipped_closed: 1,
        skipped_other: 0,
        errors: 0,
        sync_started: true,
      }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const summary = await runAtsImport(true);
    expect(summary.created).toBe(2);
    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(String(url)).toContain('/api/v2/integrations/ats/import?include_closed=true');
  });

  test('getRequisitionAtsSync GETs the per-requisition sync state', async () => {
    const fetchMock = mock(async () =>
      jsonResponse({
        linked: true,
        provider: 'workable',
        ats_status: 'OPEN',
        ats_dirty: true,
        ats_deleted: false,
        pending_changes: { role_title: 'SWE II' },
      }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const sync = await getRequisitionAtsSync('req-1');
    expect(sync.ats_dirty).toBe(true);
    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(String(url)).toContain('/api/v2/integrations/ats/requisitions/req-1/sync');
  });

  test('applyAtsUpdate and dismissAtsUpdate POST their routes', async () => {
    const fetchMock = mock(async () => jsonResponse({ applied: true }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await applyAtsUpdate('req-1');
    await dismissAtsUpdate('req-1');
    const urls = fetchMock.mock.calls.map((c) => String((c as unknown as [string])[0]));
    expect(urls[0]).toContain('/requisitions/req-1/apply-update');
    expect(urls[1]).toContain('/requisitions/req-1/dismiss-update');
  });
});
