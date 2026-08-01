// Client tests for the no-login candidate screening portal service.
//
// Mirrors public-feedback's fetch style: plain `fetch` against the v2 public
// base (no recruiter bearer/refresh). We mock `globalThis.fetch` (scoped +
// restored by test-setup.ts's backstop) and assert URL/method/body.

import { afterEach, describe, expect, mock, test } from 'bun:test';
import { ServiceError } from '@/services/service-error';
import { getContext, sendOtp, startVoice, verifyOtp } from './public-screening';

const ORIGINAL_FETCH = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = ORIGINAL_FETCH;
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('public-screening client', () => {
  test('getContext GETs the token context endpoint', async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = mock((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return Promise.resolve(
        jsonResponse({
          role_title: 'Backend Engineer',
          round_name: 'Phone Screen',
          email_hint: 'a***@ex.com',
          has_active_session: false,
        }),
      );
    }) as unknown as typeof fetch;

    const ctx = await getContext('tok-123');
    expect(ctx.role_title).toBe('Backend Engineer');
    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toContain('/api/v2/public/screening/tok-123');
    expect(calls[0]?.init?.method ?? 'GET').toBe('GET');
  });

  test('sendOtp POSTs to /send-otp', async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = mock((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return Promise.resolve(jsonResponse({ success: true, message: 'sent' }));
    }) as unknown as typeof fetch;

    await sendOtp('tok-123');
    expect(calls[0]?.url).toContain('/api/v2/public/screening/tok-123/send-otp');
    expect(calls[0]?.init?.method).toBe('POST');
  });

  test('verifyOtp POSTs {otp} to /verify-otp', async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = mock((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return Promise.resolve(jsonResponse({ success: true, session_token: 'sess-abc' }));
    }) as unknown as typeof fetch;

    const res = await verifyOtp('tok-123', '654321');
    expect(res.session_token).toBe('sess-abc');
    expect(calls[0]?.url).toContain('/api/v2/public/screening/tok-123/verify-otp');
    expect(calls[0]?.init?.method).toBe('POST');
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({ otp: '654321' });
  });

  test('startVoice POSTs {redo} to /start-voice with the session bearer', async () => {
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    globalThis.fetch = mock((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return Promise.resolve(jsonResponse({ voice_session_token: 'voice-xyz' }));
    }) as unknown as typeof fetch;

    const res = await startVoice('tok-123', 'sess-abc');
    expect(res.voice_session_token).toBe('voice-xyz');
    expect(calls[0]?.url).toContain('/api/v2/public/screening/tok-123/start-voice');
    expect(calls[0]?.init?.method).toBe('POST');
    expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({ redo: false });
    const headers = new Headers(calls[0]?.init?.headers as HeadersInit);
    expect(headers.get('Authorization')).toBe('Bearer sess-abc');
  });

  test('getContext surfaces a 410-expired error as a forbidden ServiceError with httpStatus 410', async () => {
    globalThis.fetch = mock(() =>
      Promise.resolve(jsonResponse({ detail: 'Screening link has expired' }, 410)),
    ) as unknown as typeof fetch;

    try {
      await getContext('tok-expired');
      throw new Error('expected getContext to reject');
    } catch (e) {
      expect(e).toBeInstanceOf(ServiceError);
      expect((e as ServiceError).httpStatus).toBe(410);
    }
  });
});
