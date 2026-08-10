import { getV2ApiBase } from '@/lib/env';
import { resolveV2Token, runV2UnauthorizedHandler } from '@/lib/v2-client';
import {
  type AnswerStatus,
  type CreateSessionResponse,
  type HeartbeatResponse,
  type IntakeFormData,
  type IntakeModality,
  type IntakeSession,
  type InterviewPlan,
  type ListSessionsResponse,
  type QuestionId,
  type ReprocessAcceptedResponse,
  ReprocessAlreadyRunningError,
  type SwitchModalityResponse,
  type TextStreamEvent,
  VoiceDrainFailedError,
} from '@/types/intake';

// Build an absolute backend URL from the SHARED lazy base resolver (env.ts).
// Read at call time so it reflects the env + so intake aligns with v2-client
// (one base, one fallback port, fail-loud in prod) instead of a stale
// module-load-time const.
function intakeUrl(path: string): string {
  return `${getV2ApiBase()}${path}`;
}

export type IntakeApiErrorCode =
  | 'modality_conflict'
  | 'process_running'
  | 'session_not_found'
  | 'feature_disabled'
  | 'network'
  | 'unknown';

export class IntakeApiError extends Error {
  status: number;
  detail: string;
  code?: IntakeApiErrorCode;

  constructor(status: number, detail: string, code?: IntakeApiErrorCode) {
    super(detail);
    this.name = 'IntakeApiError';
    this.status = status;
    this.detail = detail;
    if (code !== undefined) this.code = code;
  }
}

// Phase-2+ helpers (use-modality-switch, use-text-stream) throw this when the
// backend returns 409 with a modality conflict body {detail, held, requested}.
// Defined here in Phase 1 — per spec §6.7 — so all api.ts consumers share one
// import path. Extends IntakeApiError so existing `instanceof IntakeApiError`
// checks keep working.
export class ModalityConflictError extends IntakeApiError {
  readonly held: IntakeModality;
  readonly requested: IntakeModality;

  constructor(held: IntakeModality, requested: IntakeModality, detail?: string) {
    super(409, detail ?? 'another mode is currently active', 'modality_conflict');
    this.name = 'ModalityConflictError';
    this.held = held;
    this.requested = requested;
  }
}

function classifyError(status: number, detail: string): IntakeApiErrorCode {
  if (status === 403 && /not enabled/i.test(detail)) return 'feature_disabled';
  if (status === 404) return 'session_not_found';
  if (status === 409 && /process.*running/i.test(detail)) return 'process_running';
  if (status === 409) return 'modality_conflict';
  return 'unknown';
}

// Shared fetch for every intake call. Injects the bearer token from the SAME
// resolver v2-client uses, wraps network errors as IntakeApiError, and — on a
// 401 — runs the SHARED unauthorized handler (installed by v2-bootstrap) and
// replays the request exactly once with a fresh token. Before FE-F4 intake had
// no 401-refresh, so an expired token mid-intake hard-401'd while the rest of
// the app silently refreshed.
//
// `init.headers` MUST be a plain object WITHOUT Authorization — this function
// owns the auth header so the replay can carry a freshly-refreshed token.
async function intakeFetch(
  path: string,
  init: Omit<RequestInit, 'headers'> & { headers: Record<string, string> },
): Promise<Response> {
  const url = intakeUrl(path);
  const send = async (): Promise<Response> => {
    const token = await resolveV2Token();
    const headers: Record<string, string> = { ...init.headers };
    if (token) headers.Authorization = `Bearer ${token}`;
    try {
      return await fetch(url, { ...init, headers });
    } catch (e) {
      // Let AbortError propagate unchanged — callers (SSE streams) cancel via
      // AbortSignal and rely on `error.name === 'AbortError'`. Only genuine
      // network failures are normalized to IntakeApiError.
      if (e instanceof Error && e.name === 'AbortError') throw e;
      throw new IntakeApiError(0, (e as Error).message || 'network failure', 'network');
    }
  };

  const res = await send();
  if (res.status !== 401) return res;

  const refreshed = await runV2UnauthorizedHandler();
  if (!refreshed) return res;
  return send();
}

async function request<T>(
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  const res = await intakeFetch(path, {
    method,
    headers,
    credentials: 'include',
    cache: 'no-store',
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });

  if (!res.ok) {
    let detail = `request failed (${res.status})`;
    try {
      const b = (await res.json()) as { detail?: unknown };
      // Only surface a string `detail` (our domain handlers return human
      // messages as strings). Object envelopes — the safe DB error
      // {error, code}, the 500 {error, request_id}, or a 422 validation array —
      // are NEVER stringified into the UI; that leaks SQLSTATE codes and
      // internals to recruiters. Keep the generic, non-leaky fallback instead.
      if (typeof b.detail === 'string') detail = b.detail;
    } catch {
      // not JSON; keep generic
    }
    throw new IntakeApiError(res.status, detail, classifyError(res.status, detail));
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function createIntakeSession(payload: {
  form_data: IntakeFormData;
  entry_point: string | null;
}): Promise<CreateSessionResponse> {
  return request<CreateSessionResponse>('POST', '/api/v2/intake/sessions', payload);
}

// Complete-intake path for an existing requisition (ATS-imported or awaiting
// publish). The backend seeds the form from the requisition row and resumes
// the role's active session instead of duplicating it.
export function startIntakeForRole(requisitionId: string): Promise<CreateSessionResponse> {
  return request<CreateSessionResponse>('POST', '/api/v2/intake/sessions', {
    requisition_id: requisitionId,
    entry_point: 'complete_intake_btn',
  });
}

export interface JdExtractResult {
  status: 'ok' | 'rejected' | 'empty';
  source: 'text' | 'url' | 'file';
  formatted_jd: string;
  structured: {
    title: string | null;
    location: string | null;
    summary: string | null;
    responsibilities: string[];
    must_haves: string[];
    nice_to_haves: string[];
  } | null;
  flags: {
    injection_detected: boolean;
    reason: string | null;
    truncated: boolean;
    // The guardrail produced no usable verdict and was failed open. No UI reads
    // this yet; it is typed so that a screen which wants to say "we could not
    // fully check this text" does not have to widen the contract first.
    guardrail_errored?: boolean;
  };
}

// Multipart POST (browser sets the multipart boundary — do NOT set Content-Type).
// `text` (a URL inside it is auto-detected + fetched server-side) and/or `file`.
// Backend runs sanitize → injection guardrail → parse through the LLM gateway and
// returns the formatted JD (status 'rejected' on injection, 'empty' if nothing usable).
export async function extractJobDescription(
  input: { text?: string; file?: File },
  signal?: AbortSignal,
): Promise<JdExtractResult> {
  const form = new FormData();
  if (input.file) form.append('file', input.file);
  if (input.text && input.text.trim()) form.append('text', input.text);

  // No Content-Type header — the browser sets the multipart boundary itself.
  const res = await intakeFetch('/api/v2/intake/jd/extract', {
    method: 'POST',
    headers: { Accept: 'application/json' },
    credentials: 'include',
    cache: 'no-store',
    body: form,
    ...(signal ? { signal } : {}),
  });
  if (!res.ok) {
    let detail = `request failed (${res.status})`;
    try {
      const b = (await res.json()) as { detail?: unknown };
      if (typeof b.detail === 'string') detail = b.detail;
    } catch {
      // not JSON
    }
    throw new IntakeApiError(res.status, detail, classifyError(res.status, detail));
  }
  return (await res.json()) as JdExtractResult;
}

export function listIntakeSessions(): Promise<ListSessionsResponse> {
  return request<ListSessionsResponse>('GET', '/api/v2/intake/sessions');
}

export function fetchIntakeSession(sessionId: string): Promise<IntakeSession> {
  return request<IntakeSession>('GET', `/api/v2/intake/sessions/${sessionId}`);
}

export function fetchIntakeFeatureFlag(): Promise<{ intake_v2_enabled: boolean }> {
  return request<{ intake_v2_enabled: boolean }>('GET', '/api/v2/intake/feature-flag');
}

export interface PatchAnswerEntry {
  text?: string;
  status?: AnswerStatus;
}

export interface PatchAnswersResult {
  applied: QuestionId[];
}

/**
 * PATCH /api/v2/intake/sessions/:id/answers
 * Phase 2 B2.1 — manual answer edit. Server stamps manual_edit=true,
 * edited_at=now(), edited_by=user_id on every patched answer.
 *
 * Throws IntakeApiError on 4xx/5xx with the server's `detail` string.
 */
export function patchAnswers(
  sessionId: string,
  patch: Partial<Record<QuestionId, PatchAnswerEntry>>,
): Promise<PatchAnswersResult> {
  return request<PatchAnswersResult>('PATCH', `/api/v2/intake/sessions/${sessionId}/answers`, {
    patch,
  });
}

export interface VoiceStartRequest {
  sdp: string;
  type: 'offer';
}

export interface VoiceStartResponse {
  sdp: string;
  type: 'answer';
}

/**
 * POST /api/v2/intake/sessions/:id/voice/start
 * Exchanges WebRTC SDP offer for an answer via the backend proxy.
 *
 * 502 → voice agent unreachable (surface as VoiceUnavailableBanner).
 * 409 → modality conflict — IntakeApiError.code === 'modality_conflict'.
 */
export function startVoiceSession(
  sessionId: string,
  payload: VoiceStartRequest,
): Promise<VoiceStartResponse> {
  return request<VoiceStartResponse>(
    'POST',
    `/api/v2/intake/sessions/${sessionId}/voice/start`,
    payload,
  );
}

/**
 * POST a user text turn and async-iterate SSE events from the backend.
 *
 * Uses fetch + ReadableStreamDefaultReader (EventSource cannot POST a body).
 *
 * Pre-flight: if the server returns 409 BEFORE the stream opens, we throw
 * a ModalityConflictError so callers can branch without entering the stream
 * loop. All other non-2xx statuses throw IntakeApiError.
 *
 * The signal parameter lets callers cancel mid-stream (component unmount /
 * navigation). On abort the underlying fetch rejects with AbortError and the
 * generator exits via the finally block (reader.releaseLock).
 */
export function streamTextTurn(
  sessionId: string,
  message: string,
  signal?: AbortSignal,
): AsyncGenerator<TextStreamEvent, void, unknown> {
  return openSseStream(
    `/api/v2/intake/sessions/${sessionId}/text/messages`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ message }),
    },
    'text stream',
    signal,
  );
}

/**
 * POST /api/v2/intake/sessions/:id/text/opening
 *
 * Streams the agent's proactive opening greeting (no user message). Idempotent
 * server-side — yields a `done` with no text if the session already has turns.
 * Same SSE event shape as streamTextTurn.
 */
export function openTextConversation(
  sessionId: string,
  signal?: AbortSignal,
): AsyncGenerator<TextStreamEvent, void, unknown> {
  return openSseStream(
    `/api/v2/intake/sessions/${sessionId}/text/opening`,
    {
      method: 'POST',
      headers: { Accept: 'text/event-stream' },
    },
    'text opening',
    signal,
  );
}

// Open an SSE POST stream and async-iterate its parsed frames. Single home for
// the auth/base/refresh wiring + the 409-pre-flight / error-body / no-body /
// reader-loop / finally logic that streamTextTurn and openTextConversation used
// to duplicate ~95%. `errorLabel` only varies the fallback detail string.
async function* openSseStream(
  path: string,
  init: { method: string; headers: Record<string, string>; body?: BodyInit },
  errorLabel: string,
  signal?: AbortSignal,
): AsyncGenerator<TextStreamEvent, void, unknown> {
  const resp = await intakeFetch(path, {
    method: init.method,
    credentials: 'include',
    headers: init.headers,
    ...(init.body !== undefined ? { body: init.body } : {}),
    ...(signal ? { signal } : {}),
  });
  yield* consumeSseStream(resp, errorLabel);
}

/**
 * Validate an SSE Response and async-iterate its parsed `TextStreamEvent`s.
 *
 * Pre-flight gates (shared by both SSE callers):
 *  - 409              → ModalityConflictError (so callers can branch before the
 *                       reader loop).
 *  - other non-2xx    → IntakeApiError with the body's `detail` (or a generic
 *                       `<errorLabel> <status>` fallback).
 *  - missing body     → IntakeApiError(0, '<errorLabel> returned no body').
 *
 * Then a single reader loop splits on the SSE frame separator (`\n\n`), yields
 * each parsed frame, flushes a trailing unterminated frame, and releases the
 * reader lock in `finally` (which also covers AbortSignal cancellation — the
 * underlying fetch rejects with AbortError and the generator unwinds here).
 */
export async function* consumeSseStream(
  resp: Response,
  errorLabel: string,
): AsyncGenerator<TextStreamEvent, void, unknown> {
  if (resp.status === 409) {
    let detail = 'another mode is currently active';
    let held: 'voice' | 'text' | undefined;
    try {
      const body = await resp.json();
      if (typeof body?.detail === 'string') detail = body.detail;
      if (body?.held === 'voice' || body?.held === 'text') held = body.held;
    } catch {
      /* body may not be JSON */
    }
    throw new ModalityConflictError(held ?? 'voice', 'text', detail);
  }

  if (!resp.ok) {
    let detail = `${errorLabel} ${resp.status}`;
    try {
      const body = await resp.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new IntakeApiError(resp.status, detail);
  }

  if (!resp.body) {
    throw new IntakeApiError(0, `${errorLabel} returned no body`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let sepIdx: number;
      // biome-ignore lint/suspicious/noAssignInExpressions: SSE frame splitter pattern
      while ((sepIdx = buffer.indexOf('\n\n')) !== -1) {
        const rawFrame = buffer.slice(0, sepIdx);
        buffer = buffer.slice(sepIdx + 2);
        const parsed = parseSseFrame(rawFrame);
        if (parsed) yield parsed;
      }
    }
    if (buffer.trim().length > 0) {
      const parsed = parseSseFrame(buffer);
      if (parsed) yield parsed;
    }
  } finally {
    try {
      reader.releaseLock();
    } catch {
      /* releaseLock on a cancelled reader can throw */
    }
  }
}

function parseSseFrame(raw: string): TextStreamEvent | null {
  let eventName = 'message';
  const dataLines: string[] = [];
  for (const line of raw.split('\n')) {
    if (line.startsWith('event: ')) {
      eventName = line.slice('event: '.length).trim();
    } else if (line.startsWith('data: ')) {
      dataLines.push(line.slice('data: '.length));
    }
  }
  if (dataLines.length === 0) return null;

  let data: unknown;
  try {
    data = JSON.parse(dataLines.join('\n'));
  } catch {
    return null;
  }

  if (eventName === 'text' && typeof data === 'string') {
    return { type: 'text', chunk: data };
  }
  if (eventName === 'tool' && typeof data === 'object' && data !== null) {
    const d = data as { name?: string; args?: Record<string, unknown> };
    return { type: 'tool', name: d.name ?? '', args: d.args ?? {} };
  }
  if (eventName === 'done' && typeof data === 'object' && data !== null) {
    const d = data as {
      text?: string;
      stop_reason?: string | null;
      user_turn_idx?: number;
      assistant_turn_idx?: number;
    };
    return {
      type: 'done',
      text: d.text ?? '',
      stop_reason: d.stop_reason ?? null,
      user_turn_idx: d.user_turn_idx ?? -1,
      assistant_turn_idx: d.assistant_turn_idx ?? -1,
    };
  }
  if (eventName === 'error' && typeof data === 'object' && data !== null) {
    const d = data as { message?: string; code?: string };
    return {
      type: 'error',
      message: d.message ?? 'unknown',
      ...(d.code !== undefined ? { code: d.code } : {}),
    };
  }
  return null;
}

/**
 * POST /api/v2/intake/sessions/:id/switch?to=text|voice
 *
 * 200 → SwitchModalityResponse (typed union by `to`).
 * 409 → throws ModalityConflictError (defined in this file, Phase 1).
 * 502 → throws VoiceDrainFailedError.
 * Other non-2xx → throws Error with body.detail.
 */
export async function switchModality(
  sessionId: string,
  to: 'text' | 'voice',
): Promise<SwitchModalityResponse> {
  const res = await intakeFetch(`/api/v2/intake/sessions/${sessionId}/switch?to=${to}`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
  });

  if (res.status === 200) {
    return (await res.json()) as SwitchModalityResponse;
  }

  let body: {
    detail?: string;
    error?: string;
    held?: 'voice' | 'text';
    requested?: 'voice' | 'text';
  } = {};
  try {
    body = await res.json();
  } catch {
    body = { detail: (await res.text()).slice(0, 200) };
  }

  if (res.status === 409 && body.held && body.requested) {
    throw new ModalityConflictError(
      body.held,
      body.requested,
      body.detail ?? 'Another mode is currently active.',
    );
  }

  if (res.status === 502) {
    throw new VoiceDrainFailedError(
      body.detail ?? 'Voice agent did not drain cleanly — please try again.',
      body.error,
    );
  }

  throw new Error(body.detail ?? `Switch to ${to} failed: ${res.status}`);
}

/**
 * POST /api/v2/intake/sessions/:id/reprocess
 *
 * 202 → {session_id, process_run_id}.
 * 409 → throws ReprocessAlreadyRunningError.
 * Other non-2xx → throws Error with body.detail.
 */
export async function reprocessSession(sessionId: string): Promise<ReprocessAcceptedResponse> {
  const res = await intakeFetch(`/api/v2/intake/sessions/${sessionId}/reprocess`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
  });

  if (res.status === 202) {
    return (await res.json()) as ReprocessAcceptedResponse;
  }

  let body: { detail?: string } = {};
  try {
    body = await res.json();
  } catch {
    body = { detail: (await res.text()).slice(0, 200) };
  }

  if (res.status === 409) {
    throw new ReprocessAlreadyRunningError(
      body.detail ?? 'Reprocess already running for this session.',
    );
  }

  throw new Error(body.detail ?? `Reprocess failed: ${res.status}`);
}

/**
 * End the active conversation by clearing active_modality to null (B3.1).
 */
export async function endConversation(sessionId: string): Promise<{
  active_modality: null;
  session: IntakeSession;
}> {
  const resp = await intakeFetch(`/api/v2/intake/sessions/${sessionId}/switch?to=none`, {
    method: 'POST',
    credentials: 'include',
    headers: { Accept: 'application/json' },
  });

  if (!resp.ok) {
    let detail = `endConversation ${resp.status}`;
    try {
      const body = await resp.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new IntakeApiError(resp.status, detail);
  }
  return resp.json();
}

export interface SubmitResponse {
  session_id: string;
  status: string;
}

export interface PublishResponse {
  session_id: string;
  requisition_id: string;
  redirect_url: string;
}

/**
 * POST /api/v2/intake/sessions/:id/submit
 * Phase 5 T2 — marks the session submitted and kicks off post-processing.
 * Server returns 202 with {session_id, status}. Errors normalize through
 * IntakeApiError (e.g. 409 already submitted, 500 lambda failure).
 */
export function submitSession(sessionId: string): Promise<SubmitResponse> {
  return request<SubmitResponse>('POST', `/api/v2/intake/sessions/${sessionId}/submit`);
}

/**
 * POST /api/v2/intake/sessions/:id/publish
 * Phase 5 T2 — finalises the session into a requisition + interview plan.
 * Pass `editedPlan` when the user tweaked the proposed plan; otherwise we
 * send `interview_plan: null` so the backend keeps the server-side draft.
 */
export function publishSession(
  sessionId: string,
  editedPlan?: InterviewPlan,
): Promise<PublishResponse> {
  return request<PublishResponse>('POST', `/api/v2/intake/sessions/${sessionId}/publish`, {
    interview_plan: editedPlan ?? null,
  });
}

// --------------------------------------------------------------
// Session heartbeat (keeps the modality lock alive during a live call)
// --------------------------------------------------------------

export function postSessionHeartbeat(
  sessionId: string,
  paused: boolean,
): Promise<HeartbeatResponse> {
  return request<HeartbeatResponse>(
    'POST',
    `/api/v2/intake/sessions/${sessionId}/heartbeat?paused=${paused ? 'true' : 'false'}`,
  );
}
