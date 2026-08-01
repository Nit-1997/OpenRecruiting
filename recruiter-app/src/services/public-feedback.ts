// Public interviewer-feedback portal service.
//
// This is a SEPARATE auth domain from the recruiter app: interviewers are not
// logged in. Auth is a short-lived "feedback session" JWT minted by the backend
// (OTP / openrecruiting-auth) and held in sessionStorage (per-tab), sent as
// `Authorization: Bearer <session_token>`. We deliberately do NOT reuse
// `v2Client` — its 401 handler tries to refresh the recruiter Supabase session,
// which is wrong here. Plain fetch, no recruiter token getter.

import { getV2ApiBase } from '@/lib/env';
import { ServiceError } from '@/services/service-error';

// Resolve the base at call time, not module load. getV2ApiBase() THROWS in
// production when the base env is unset; evaluating it at module scope would
// crash the import of every /feedback/[token]/* page instead of failing one
// request cleanly (mirrors lib/intake/api.ts's intakeUrl() pattern).
function feedbackBase(): string {
  return `${getV2ApiBase()}/api/v2/public/feedback`;
}

// ---- response/request types (mirror backend v2 models/feedback.py) ----

export interface FeedbackContext {
  requires_otp: boolean;
  requires_platform_login: boolean;
  has_active_session: boolean;
  candidate_name?: string | null;
  round_name?: string | null;
  email_hint?: string | null;
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

export interface FeedbackQuestion {
  question_number: number;
  heading: string;
  description?: string | null;
}

export interface FeedbackSession {
  candidate_name: string;
  candidate_email: string;
  round_name: string;
  round_type: string;
  interview_date?: string | null;
  has_transcript: boolean;
  has_scorecard: boolean;
  existing_transcript?: string | null;
  has_existing_feedback: boolean;
  questions?: FeedbackQuestion[] | null;
}

export interface QuestionSummary {
  question_number: number;
  question_text: string;
  description?: string | null;
  summary?: string | null;
}

export type FeedbackRating = 'strong_yes' | 'yes' | 'maybe' | 'no' | 'strong_no';

export interface FeedbackReview {
  candidate_round_id: string;
  candidate_name: string;
  round_name: string;
  interview_date?: string | null;
  processing_status: string;
  summary?: string | null;
  rating?: FeedbackRating | null;
  question_summaries?: QuestionSummary[] | null;
  can_edit: boolean;
  is_approved: boolean;
  approved_at?: string | null;
  feedback_voice_session_status?: string | null;
  feedback_voice_session_error?: string | null;
}

export interface FeedbackEditPayload {
  summary?: string;
  rating?: FeedbackRating;
  question_summaries?: Record<string, string>;
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
    res = await fetch(`${feedbackBase()}${path}`, {
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
    const code =
      res.status === 404
        ? 'not_found'
        : res.status === 403 || res.status === 401
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

/** Bootstrap — token-only, no session. Tells us which auth gate to render. */
export function getContext(token: string): Promise<FeedbackContext> {
  return request<FeedbackContext>(`/${token}`);
}

export function sendOtp(token: string): Promise<SendOtpResult> {
  return request<SendOtpResult>(`/${token}/send-otp`, { method: 'POST' });
}

export function verifyOtp(token: string, otp: string): Promise<VerifyOtpResult> {
  return request<VerifyOtpResult>(`/${token}/verify-otp`, {
    method: 'POST',
    body: { otp },
  });
}

/** Registered OpenRecruiting interviewers: exchange their Supabase access token. */
export function platformAuth(token: string, supabaseAccessToken: string): Promise<VerifyOtpResult> {
  return request<VerifyOtpResult>(`/${token}/openrecruiting-auth`, {
    method: 'POST',
    body: {},
    sessionToken: supabaseAccessToken,
  });
}

export function getSession(token: string, sessionToken: string): Promise<FeedbackSession> {
  return request<FeedbackSession>(`/${token}/session`, { sessionToken });
}

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

export function getReview(token: string, sessionToken: string): Promise<FeedbackReview> {
  return request<FeedbackReview>(`/${token}/review`, { sessionToken });
}

export function editFeedback(
  token: string,
  sessionToken: string,
  payload: FeedbackEditPayload,
): Promise<{ success: boolean; message: string }> {
  return request(`/${token}/edit`, {
    method: 'PUT',
    body: payload,
    sessionToken,
  });
}

export function approveFeedback(
  token: string,
  sessionToken: string,
): Promise<{ success: boolean; message: string; approved_at?: string | null }> {
  return request(`/${token}/approve`, { method: 'POST', body: {}, sessionToken });
}
