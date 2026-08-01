// Phase 3 Task 3.3 — deep-link role-title resolution.
//
// Under v2 a real production requisition id has NO fixture, so the canvas must
// resolve the display title from the `title` query param (supplied by the role
// tab's "Generate in agent" link) instead of `REQS.find`. We drive the REAL
// canvas + real zustand stores against a scoped `globalThis.fetch` mock and a
// controllable `next/navigation`, asserting the session initializes
// candidate_pick with the title from the param — for a uuid absent from REQS.

import { afterAll, afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { cleanup, render, waitFor } from '@testing-library/react';
import { useSessionStore } from '@/stores';

const ORIGINAL_FETCH = globalThis.fetch;
const ORIGINAL_V2_URL = process.env.NEXT_PUBLIC_API_V2_URL;

// A uuid that is guaranteed NOT to be in REQS (fixture ids are short slugs).
const REAL_ROLE_ID = '00000000-1111-2222-3333-444444444444';

let searchParamsValue = new URLSearchParams();

mock.module('next/navigation', () => ({
  useRouter: () => ({
    push: () => {},
    replace: () => {},
    back: () => {},
    forward: () => {},
    refresh: () => {},
    prefetch: () => {},
  }),
  usePathname: () => '/debrief',
  useSearchParams: () => searchParamsValue,
}));

function jsonResponse(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
    ...init,
  });
}

function forceV2(): void {
  process.env.NEXT_PUBLIC_V2_API = 'true';
  process.env.NEXT_PUBLIC_API_V2_URL = 'http://backend.test';
}

// Import AFTER the next/navigation mock is registered.
const { DebriefCanvas } = await import('./canvas');

beforeEach(() => {
  useSessionStore.getState().reset();
  if (typeof localStorage !== 'undefined') localStorage.clear();
  searchParamsValue = new URLSearchParams();
  // The candidate-pick stage fetches the candidate list once it mounts; return
  // an empty list so the init chain settles without a network error.
  globalThis.fetch = mock(async () => jsonResponse([])) as unknown as typeof fetch;
});

afterEach(() => {
  cleanup();
  globalThis.fetch = ORIGINAL_FETCH;
});

afterAll(() => {
  process.env.NEXT_PUBLIC_V2_API = 'false';
  if (ORIGINAL_V2_URL === undefined) delete process.env.NEXT_PUBLIC_API_V2_URL;
  else process.env.NEXT_PUBLIC_API_V2_URL = ORIGINAL_V2_URL;
});

describe('DebriefCanvas — deep-link role-title resolution (Task 3.3)', () => {
  test('v2 + ?role=<uuid>&title=Senior PM initializes candidate_pick with the param title (no fixture)', async () => {
    forceV2();
    searchParamsValue = new URLSearchParams(
      `role=${REAL_ROLE_ID}&title=${encodeURIComponent('Senior PM')}`,
    );

    render(<DebriefCanvas id="debrief-canvas" />);

    await waitFor(() => {
      const s = useSessionStore.getState().sessions.debrief;
      expect(s?.selections.roleId).toBe(REAL_ROLE_ID);
    });

    const s = useSessionStore.getState().sessions.debrief;
    expect(s?.selections.roleTitle).toBe('Senior PM');
    expect(s?.stage).toBe('candidate_pick');
    // The user-echo message uses the resolved title (proves no fixture lookup).
    expect(s?.messages.some((m) => m.role === 'user' && m.text.includes('Senior PM'))).toBe(true);
  });

  test('v2 + a missing title falls back to "this role" (never silently bails)', async () => {
    forceV2();
    searchParamsValue = new URLSearchParams(`role=${REAL_ROLE_ID}`);

    render(<DebriefCanvas id="debrief-canvas" />);

    await waitFor(() => {
      const s = useSessionStore.getState().sessions.debrief;
      expect(s?.selections.roleId).toBe(REAL_ROLE_ID);
    });

    const s = useSessionStore.getState().sessions.debrief;
    expect(s?.selections.roleTitle).toBe('this role');
    expect(s?.stage).toBe('candidate_pick');
  });
});
