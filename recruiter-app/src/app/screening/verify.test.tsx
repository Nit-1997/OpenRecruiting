// FE coverage for the candidate screening VERIFY page.
//
// next/navigation is mocked process-wide (test-setup.ts). We re-register it here
// reading from mutable fixtures (token + a captured `replace` spy) — the same
// non-polluting pattern use-shell-sync.test.tsx uses — and restore the defaults
// in afterAll so the process-wide last-writer-wins mock stays harmless for any
// file scheduled after this one.
//
// We drive the real public-screening client by mocking `globalThis.fetch`
// (scoped + restored by test-setup.ts's backstop) rather than full-replacing the
// service module, per the repo's mock.module caution.

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

import ScreeningVerifyPage from './[token]/verify/page';

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

describe('ScreeningVerifyPage', () => {
  test('410 from getContext renders the expired state', async () => {
    routeFetch({
      '/public/screening/tok-1': { status: 410, body: { detail: 'Screening link has expired' } },
    });

    const { container } = render(<ScreeningVerifyPage />);

    await waitFor(() => {
      expect(container.querySelector('#screening-verify-expired')).not.toBeNull();
    });
    expect(container.querySelector('#screening-verify-expired')?.textContent ?? '').toContain(
      'expired',
    );
  });

  test('valid OTP verifies and replaces to the call page', async () => {
    // send-otp matched first (more specific), then verify-otp, then context.
    routeFetch({
      '/verify-otp': { body: { success: true, session_token: 'sess-xyz' } },
      '/send-otp': { body: { success: true, message: 'sent', retry_after_seconds: 60 } },
      '/public/screening/tok-1': {
        body: {
          role_title: 'Backend Engineer',
          round_name: 'Phone Screen',
          email_hint: 'a***@ex.com',
          has_active_session: false,
        },
      },
    });

    const { container } = render(<ScreeningVerifyPage />);

    // Wait for the OTP inputs to render after bootstrap + auto-send.
    await waitFor(() => {
      expect(container.querySelector('#screening-otp-0')).not.toBeNull();
    });

    // Fill all six digits — the last change auto-submits.
    for (let i = 0; i < 6; i++) {
      const input = container.querySelector(`#screening-otp-${i}`) as HTMLInputElement;
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        'value',
      )?.set;
      setter?.call(input, '1');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }

    await waitFor(() => {
      expect(replaceCalls).toContain('/screening/tok-1/call');
    });
  });

  test('lockout from verify renders the locked state', async () => {
    const lockedUntil = new Date(Date.now() + 120_000).toISOString();
    routeFetch({
      '/verify-otp': {
        body: { success: false, locked_until: lockedUntil, attempts_remaining: 0 },
      },
      '/send-otp': { body: { success: true, message: 'sent', retry_after_seconds: 60 } },
      '/public/screening/tok-1': {
        body: {
          role_title: 'Backend Engineer',
          round_name: 'Phone Screen',
          email_hint: 'a***@ex.com',
          has_active_session: false,
        },
      },
    });

    const { container } = render(<ScreeningVerifyPage />);

    await waitFor(() => {
      expect(container.querySelector('#screening-otp-0')).not.toBeNull();
    });

    for (let i = 0; i < 6; i++) {
      const input = container.querySelector(`#screening-otp-${i}`) as HTMLInputElement;
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        'value',
      )?.set;
      setter?.call(input, '1');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }

    await waitFor(() => {
      expect(container.querySelector('#screening-verify-locked')).not.toBeNull();
    });
  });
});
