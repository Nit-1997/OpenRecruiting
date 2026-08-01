/**
 * Service test for the debrief insight summary. The v2 path derives the
 * role-level summary from the newest packet's timestamp — previously it
 * interpolated the RAW ISO string ("...generated 2026-06-08T02:41:54Z..."),
 * which leaked into the UI. It now renders the human-readable relative time via
 * the shared `relativeTimeFrom` helper. We drive the real service against a
 * scoped `globalThis.fetch` mock (FE invariant: mock fetch, not the module).
 */

import { afterAll, afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import type { PacketListItem } from '@/lib/debrief/api';
import { getInsights } from './debrief';

const ORIGINAL_FETCH = globalThis.fetch;
const ORIGINAL_V2_URL = process.env.NEXT_PUBLIC_API_V2_URL;

const ISO_PATTERN = /\d{4}-\d{2}-\d{2}T/;

function packetListItem(overrides: Partial<PacketListItem> = {}): PacketListItem {
  return {
    packet_id: 'pkt-1',
    status: 'fresh',
    candidate_ids: ['c1', 'c2'],
    verdict: 'hire',
    confidence: 'high',
    generated_at: new Date(Date.now() - 2 * 60_000).toISOString(),
    created_at: new Date(Date.now() - 5 * 60_000).toISOString(),
    ...overrides,
  };
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_V2_URL = 'http://backend.test';
  process.env.NEXT_PUBLIC_V2_API = 'true';
});

afterEach(() => {
  globalThis.fetch = ORIGINAL_FETCH;
});

afterAll(() => {
  process.env.NEXT_PUBLIC_V2_API = 'false';
  if (ORIGINAL_V2_URL === undefined) delete process.env.NEXT_PUBLIC_API_V2_URL;
  else process.env.NEXT_PUBLIC_API_V2_URL = ORIGINAL_V2_URL;
});

describe('getInsights — relative-time summary (no raw ISO)', () => {
  test('renders the relative time, never the raw ISO timestamp', async () => {
    globalThis.fetch = mock(async () =>
      jsonResponse([packetListItem()]),
    ) as unknown as typeof fetch;

    const insight = await getInsights('r1');

    expect(insight.summary).toContain('2m ago');
    expect(insight.summary).toContain('Open it to review the recommendation.');
    // The headline must NOT leak a raw ISO string.
    expect(insight.summary).not.toMatch(ISO_PATTERN);
  });

  test('falls back to created_at (still relative) when generated_at is null', async () => {
    globalThis.fetch = mock(async () =>
      jsonResponse([
        packetListItem({
          generated_at: null,
          created_at: new Date(Date.now() - 3 * 60 * 60_000).toISOString(),
        }),
      ]),
    ) as unknown as typeof fetch;

    const insight = await getInsights('r1');

    expect(insight.summary).toContain('3h ago');
    expect(insight.summary).not.toMatch(ISO_PATTERN);
  });

  test('an empty packet list yields the neutral prompt (no timestamp)', async () => {
    globalThis.fetch = mock(async () => jsonResponse([])) as unknown as typeof fetch;

    const insight = await getInsights('r1');

    expect(insight.summary).toContain('No debrief packets yet');
    expect(insight.summary).not.toMatch(ISO_PATTERN);
  });
});
