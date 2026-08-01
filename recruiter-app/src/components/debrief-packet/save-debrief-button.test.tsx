// The packet-toolbar Save action (moved from the chat result stage).
//
// Drives the REAL SaveDebriefButton against a scoped `globalThis.fetch` mock (so
// the genuine `saveDebrief` runs) and a controllable `next/navigation` router. We
// assert: a Save click commits the packet then navigates to the role deep-link;
// an error surfaces a message and does NOT navigate; the button disables while
// saving.

import { afterAll, afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react';

const ORIGINAL_FETCH = globalThis.fetch;
const ORIGINAL_V2_URL = process.env.NEXT_PUBLIC_API_V2_URL;

const pushMock = mock((_: string) => {});

mock.module('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
  usePathname: () => '/debrief',
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
const { SaveDebriefButton } = await import('./save-debrief-button');

function renderButton() {
  return render(<SaveDebriefButton id="debrief-result" packetId="packet-9" roleId="role-xyz" />);
}

beforeEach(() => {
  pushMock.mockClear();
  forceV2();
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

describe('SaveDebriefButton — commit + handoff', () => {
  test('clicking Save commits the packet then navigates to the role deep-link', async () => {
    let savedUrl = '';
    globalThis.fetch = mock(async (url: string) => {
      savedUrl = String(url);
      return jsonResponse({ packet_id: 'packet-9', status: 'fresh' });
    }) as unknown as typeof fetch;

    renderButton();

    const save = document.getElementById('debrief-result-save') as HTMLButtonElement;
    expect(save).not.toBeNull();
    fireEvent.click(save);

    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith('/view/roles/role-xyz?debrief=packet-9');
    });
    expect(savedUrl).toBe('http://backend.test/api/v2/debrief/packets/packet-9/save');
  });

  test('an error surfaces a message and does NOT navigate', async () => {
    globalThis.fetch = mock(async () =>
      jsonResponse({ detail: 'conflict' }, { status: 409 }),
    ) as unknown as typeof fetch;

    renderButton();

    const save = document.getElementById('debrief-result-save') as HTMLButtonElement;
    fireEvent.click(save);

    await waitFor(() => {
      const err = document.getElementById('debrief-result-save-error');
      expect(err?.textContent).toBeTruthy();
    });
    expect(pushMock).not.toHaveBeenCalled();
  });
});
