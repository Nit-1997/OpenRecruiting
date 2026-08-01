// Public, no-login candidate screening portal service.
//
// SEPARATE auth domain from the recruiter app: screening candidates are external
// and not logged in. Auth is a short-lived "screening session" JWT minted by the
// backend (OTP) and held in sessionStorage (per-tab), sent as
// `Authorization: Bearer <session_token>`. We deliberately do NOT reuse
// `v2Client` — its 401 handler tries to refresh the recruiter Supabase session,
// which is wrong here. Plain fetch, no recruiter token getter. Mirrors
// `public-feedback.ts` exactly.

import { getV2ApiBase } from '@/lib/env';
import { ServiceError } from '@/services/service-error';

// Resolve the base at call time, not module load. getV2ApiBase() THROWS in
// production when the base env is unset; evaluating it at module scope would
// crash the import of every /screening/[token]/* page instead of failing one
// request cleanly (mirrors public-feedback.ts's feedbackBase()).
function screeningBase(): string {
  return `${getV2ApiBase()}/api/v2/public/screening`;
}

// HTTP status the backend returns when the invite's link window has elapsed.
// The verify page keys its dedicated "expired" stage on this.
export const SCREENING_EXPIRED_STATUS = 410;

// ---- response/request types (mirror backend schemas/screening.py) -----

export interface ScreeningContext {
  role_title?: string | null;
  round_name?: string | null;
  email_hint?: string | null;
  has_active_session: boolean;
}

export interface SendOtpResult {
  success: boolean;
  message: string;
  email_hint?: string | null;
  retry_after_seconds?: number | null;
}

export interface VerifyOtpResult {
  success: boolean;
  session_token?: string | null;
  error?: string | null;
  locked_until?: string | null;
  attempts_remaining?: number | null;
}

export interface ScreeningSession {
  valid: boolean;
  role_title?: string | null;
  round_name?: string | null;
  candidate_email?: string | null;
}

// ---------------------------- fetch plumbing --------------------------------

async function request<T>(
  path: string,
  opts: { method?: string; body?: unknown; sessionToken?: string | null } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
  if (opts.sessionToken) headers.Authorization = `Bearer ${opts.sessionToken}`;

  let res: Response;
  try {
    res = await fetch(`${screeningBase()}${path}`, {
      method: opts.method ?? 'GET',
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : null,
      cache: 'no-store',
    });
  } catch (e) {
    throw new ServiceError('network', 'Network error — please try again.', {
      rawDetail: e instanceof Error ? e.message : String(e),
    });
  }

  if (res.status === 204) return undefined as T;

  let payload: unknown = null;
  try {
    payload = await res.json();
  } catch {
    payload = null;
  }

  if (!res.ok) {
    const detail =
      payload && typeof payload === 'object' && 'detail' in payload
        ? String((payload as { detail: unknown }).detail)
        : `Request failed (${res.status})`;
    // 410 = expired link window. There is no 'gone' ServiceErrorCode, so we map
    // it to 'forbidden' for the shared union but always carry httpStatus=410 so
    // the verify page can branch to its dedicated "expired" stage.
    const code =
      res.status === 404
        ? 'not_found'
        : res.status === 410 || res.status === 403 || res.status === 401
          ? 'forbidden'
          : res.status === 409
            ? 'conflict'
            : res.status === 422
              ? 'validation'
              : 'internal';
    throw new ServiceError(code, detail, { httpStatus: res.status, rawDetail: detail });
  }

  return payload as T;
}

// ------------------------------- endpoints ----------------------------------

/** Bootstrap — token-only, no session. 410 ServiceError if the link expired. */
export function getContext(token: string): Promise<ScreeningContext> {
  return request<ScreeningContext>(`/${token}`);
}

export function sendOtp(token: string): Promise<SendOtpResult> {
  return request<SendOtpResult>(`/${token}/send-otp`, { method: 'POST' });
}

/** Verify the 6-digit OTP. 410 ServiceError if the link expired. */
export function verifyOtp(token: string, otp: string): Promise<VerifyOtpResult> {
  return request<VerifyOtpResult>(`/${token}/verify-otp`, {
    method: 'POST',
    body: { otp },
  });
}

export function getSession(token: string, sessionToken: string): Promise<ScreeningSession> {
  return request<ScreeningSession>(`/${token}/session`, { sessionToken });
}

/** Session-gated: mint a voice-agent session token for the screening call. */
export function startVoice(
  token: string,
  sessionToken: string,
  redo = false,
): Promise<{ voice_session_token: string }> {
  return request<{ voice_session_token: string }>(`/${token}/start-voice`, {
    method: 'POST',
    body: { redo },
    sessionToken,
  });
}
