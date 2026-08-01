// FE coverage for the candidate screening CALL page.
//
// Same non-polluting pattern as verify.test.tsx: re-register next/navigation from
// mutable fixtures and restore in afterAll. We drive the real public-screening
// client via a scoped globalThis.fetch mock. The WebRTC provider itself is mocked
// (no real transport in jsdom/happy-dom) so we can assert the start handler calls
// startVoice -> call.start, and that a missing session redirects to verify.

import { afterAll, afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { cleanup, render, waitFor } from '@testing-library/react';

let tokenFixture = 'tok-1';
const replaceCalls: string[] = [];

mock.module('next/navigation', () => ({
  useRouter: () => ({
    push: () => {},
    replace: (href: string) => {
      replaceCalls.push(href);
    },
    back: () => {},
    forward: () => {},
    refresh: () => {},
    prefetch: () => {},
  }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({ token: tokenFixture }),
}));

// Mock the call provider one layer deep: a real React provider/context shell would
// be heavy, so expose a fake hook + passthrough provider. start() records the voice
// token it was handed so we can assert startVoice -> call.start wiring.
const startCalls: string[] = [];
mock.module('@/components/screening/screening-call-provider', () => ({
  ScreeningCallProvider: ({ children }: { children: React.ReactNode }) => children,
  useScreeningCall: () => ({
    status: 'idle' as const,
    isMuted: false,
    lastError: null,
    statusRef: { current: 'idle' as const },
    transcript: [],
    botInterim: '',
    start: (voiceSessionToken: string) => {
      startCalls.push(voiceSessionToken);
      return Promise.resolve();
    },
    end: () => Promise.resolve(),
    toggleMute: () => {},
  }),
}));

import ScreeningCallPage from './[token]/call/page';

const ORIGINAL_FETCH = globalThis.fetch;

interface RouteHandler {
  status?: number;
  body: unknown;
}

function routeFetch(routes: Record<string, RouteHandler>) {
  globalThis.fetch = mock((url: string) => {
    for (const [needle, handler] of Object.entries(routes)) {
      if (url.includes(needle)) {
        return Promise.resolve(
          new Response(JSON.stringify(handler.body), {
            status: handler.status ?? 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        );
      }
    }
    return Promise.resolve(new Response(JSON.stringify({ detail: 'unmatched' }), { status: 500 }));
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  tokenFixture = 'tok-1';
  replaceCalls.length = 0;
  startCalls.length = 0;
  try {
    window.sessionStorage.clear();
  } catch {
    /* ignore */
  }
});

afterEach(() => {
  cleanup();
  globalThis.fetch = ORIGINAL_FETCH;
});

afterAll(() => {
  tokenFixture = 'tok-1';
});

describe('ScreeningCallPage', () => {
  test('no session redirects to the verify page', async () => {
    routeFetch({
      '/public/screening/tok-1': {
        body: {
          role_title: 'Backend Engineer',
          round_name: 'Phone Screen',
          has_active_session: false,
        },
      },
    });

    render(<ScreeningCallPage />);

    await waitFor(() => {
      expect(replaceCalls).toContain('/screening/tok-1/verify');
    });
  });

  test('with a session, renders the pre-call screen and Start triggers startVoice + call.start', async () => {
    window.sessionStorage.setItem('screening_session_tok-1', 'sess-abc');
    routeFetch({
      '/start-voice': { body: { voice_session_token: 'voice-tok-9' } },
      '/public/screening/tok-1': {
        body: {
          role_title: 'Backend Engineer',
          round_name: 'Phone Screen',
          has_active_session: true,
        },
      },
    });

    const { container } = render(<ScreeningCallPage />);

    await waitFor(() => {
      expect(container.querySelector('#screening-start-call')).not.toBeNull();
    });

    const startBtn = container.querySelector('#screening-start-call') as HTMLButtonElement;
    startBtn.dispatchEvent(new MouseEvent('click', { bubbles: true }));

    await waitFor(() => {
      expect(startCalls).toContain('voice-tok-9');
    });
  });
});
