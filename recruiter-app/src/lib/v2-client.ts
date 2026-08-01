// Thin fetch wrapper for the v2 backend.
//
// Design notes:
// - Plain async functions — no React Query / SWR. The v2 service layer already
//   manages refetch through the named-event bus per spec §10.
// - `cache: 'no-store'` on every call: recruiter dashboard, freshness wins.
// - Bearer token is fetched via a pluggable getter (`setV2TokenGetter`). This
//   keeps the lib free of a hard `@supabase/ssr` dependency in recruiter-app
//   (which does not yet integrate Supabase auth). Production wiring will call
//   `setV2TokenGetter(async () => (await supabase.auth.getSession())
//     .data.session?.access_token ?? null)` once at app boot.
// - `If-Match` is accepted as an optional request option for the reorder
//   endpoint, which uses the header for optimistic concurrency.
// - 412 (precondition failed) on reorder is special-cased into a helpful
//   `ServiceError('conflict', …)` so the UI can prompt a refresh; the caller
//   is responsible for issuing the actual refetch via the event bus.

import { ServiceError } from '@/services/service-error';
import { getV2ApiBase } from './env';

export type TokenGetter = () => Promise<string | null> | string | null;

let tokenGetter: TokenGetter = async () => null;

export function setV2TokenGetter(fn: TokenGetter): void {
  tokenGetter = fn;
}

// Optional 401 hook. When set, the client calls this on a 401 response. If it
// resolves true, the request is retried exactly once with a fresh token. If
// false (or unset), the 401 is surfaced as a `ServiceError('forbidden', …)`.
//
// Defined here as a pluggable hook (mirror of `setV2TokenGetter`) so the
// v2-client doesn't have to import from `@/stores`, which would create a cycle
// (auth-store doesn't import v2-client today, but bootstrap code wires both).
export type UnauthorizedHandler = () => Promise<boolean>;

let unauthorizedHandler: UnauthorizedHandler | null = null;

export function setV2UnauthorizedHandler(fn: UnauthorizedHandler | null): void {
  unauthorizedHandler = fn;
}

export interface V2RequestOptions {
  /** Sent as `If-Match` header (reorder endpoint only). */
  ifMatch?: string;
  /** Override the token getter for a single call (mostly used in tests). */
  token?: string | null;
  /**
   * Optional grouping ID, sent as `X-Correlation-ID`. Use to tie together a
   * multi-step recruiter action (e.g. "schedule + load packet + open
   * drawer") so backend log lines can be filtered on a single ID. If
   * omitted, no correlation header is sent — request_id alone is enough
   * for single-call triage.
   */
  correlationId?: string;
}

export interface V2ApiErrorPayload {
  status: number;
  code?: string;
  detail?: string;
  /** UUID echoed in the response's X-Request-ID. Surfaced on errors so the
   *  user (or our error tracker) can paste it into a bug report. */
  requestId?: string;
}

export class V2ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly detail?: string;
  readonly requestId?: string;

  constructor(payload: V2ApiErrorPayload) {
    super(payload.detail ?? `v2 API error (${payload.status})`);
    this.name = 'V2ApiError';
    this.status = payload.status;
    if (payload.code !== undefined) this.code = payload.code;
    if (payload.detail !== undefined) this.detail = payload.detail;
    if (payload.requestId !== undefined) this.requestId = payload.requestId;
  }
}

// crypto.randomUUID is widely available in modern browsers and Node 19+.
// Falls back to a math-random UUID4 if not present (older browsers, tests
// in a constrained environment). The fallback is not cryptographically
// strong but is sufficient for correlating logs.
function generateRequestId(): string {
  const cryptoObj = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (cryptoObj?.randomUUID) {
    return cryptoObj.randomUUID();
  }
  // RFC4122 v4-style fallback.
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// Resolve the bearer token from the registered getter (or null). Exported so
// other v2-aware callers (intake/api.ts) share the SAME token source + the SAME
// 401-refresh wiring installed by v2-bootstrap, instead of re-reading
// supabase.getSession() on their own.
export async function resolveV2Token(): Promise<string | null> {
  try {
    const out = await Promise.resolve(tokenGetter());
    return out ?? null;
  } catch {
    return null;
  }
}

// Run the registered 401 handler exactly once. Returns true if it refreshed the
// session (caller should replay), false otherwise (no handler, threw, or it
// declined). Shared with intake/api.ts so an expired token mid-intake refreshes
// the same way the rest of the app does.
export async function runV2UnauthorizedHandler(): Promise<boolean> {
  if (!unauthorizedHandler) return false;
  try {
    return await unauthorizedHandler();
  } catch {
    return false;
  }
}

async function resolveToken(opts?: V2RequestOptions): Promise<string | null> {
  if (opts && 'token' in opts) return opts.token ?? null;
  return resolveV2Token();
}

function buildUrl(path: string): string {
  // Path may be absolute (`/api/v2/...`) or relative (`api/v2/...`). Normalize.
  const trimmedBase = getV2ApiBase().replace(/\/+$/, '');
  const trimmedPath = path.startsWith('/') ? path : `/${path}`;
  return `${trimmedBase}${trimmedPath}`;
}

async function parseError(res: Response): Promise<V2ApiErrorPayload> {
  let detail: string | undefined;
  let code: string | undefined;
  try {
    const body = (await res.json()) as { detail?: unknown; code?: unknown };
    if (typeof body.detail === 'string') detail = body.detail;
    else if (body.detail !== undefined) detail = JSON.stringify(body.detail);
    if (typeof body.code === 'string') code = body.code;
  } catch {
    // not JSON; swallow
  }
  const requestId = res.headers.get('X-Request-ID') ?? undefined;
  const payload: V2ApiErrorPayload = { status: res.status };
  if (code !== undefined) payload.code = code;
  if (detail !== undefined) payload.detail = detail;
  if (requestId !== undefined) payload.requestId = requestId;
  return payload;
}

// Map an HTTP status to a ServiceError so existing UI toasts (which key off
// ServiceErrorCode) keep working unchanged. requestId is carried through
// for triage — log/toast consumers can include it in their output.
//
// User-facing copy rules:
//  - 4xx (validation/conflict/not_found/forbidden): the backend's `detail`
//    is intentionally user-facing copy (e.g. "A candidate with this email
//    already exists in this role."). Surface it as-is.
//  - 5xx: the backend's `detail` is implementation noise (e.g. raw
//    "RPC error: 42704 constraint ..."). Replace with a generic friendly
//    message. The raw detail is stashed on `ServiceError.rawDetail` so
//    consumers can console.warn / capture it for triage WITHOUT showing
//    it to the user.
function toServiceError(err: V2ApiErrorPayload): ServiceError {
  const detail = err.detail ?? `Request failed with ${err.status}`;
  // Build options conditionally — exactOptionalPropertyTypes rejects an
  // explicit `undefined` for optional fields, so only include requestId
  // when we actually have one.
  const base: { httpStatus: number; requestId?: string; rawDetail?: string } = {
    httpStatus: err.status,
  };
  if (err.requestId !== undefined) base.requestId = err.requestId;
  if (err.detail !== undefined) base.rawDetail = err.detail;

  if (err.status === 400 || err.status === 422) {
    return new ServiceError('validation', detail, base);
  }
  if (err.status === 401 || err.status === 403) {
    return new ServiceError('forbidden', detail, base);
  }
  if (err.status === 404) {
    return new ServiceError('not_found', detail, base);
  }
  if (err.status === 409) {
    return new ServiceError('conflict', detail, base);
  }
  if (err.status === 412 || err.status === 428) {
    // Precondition failed (stale If-Match on reorder) — surface as conflict.
    return new ServiceError('conflict', 'Plan was modified by another user — please retry.', base);
  }
  if (err.status >= 500) {
    // Log the raw backend detail so devs can triage from the browser
    // console, but never surface it to the user — the message is generic.
    if (err.detail) {
      // biome-ignore lint/suspicious/noConsole: deliberate triage log
      console.warn(`[v2-client] ${err.status} ${err.requestId ?? '-'}: ${err.detail}`);
    }
    return new ServiceError('internal', 'Something went wrong. Please try again.', base);
  }
  return new ServiceError('internal', detail, base);
}

interface ExecuteRequestArgs {
  method: string;
  url: string;
  body: unknown;
  token: string | null;
  ifMatch: string | undefined;
  requestId: string;
  correlationId: string | undefined;
}

async function executeRequest(args: ExecuteRequestArgs): Promise<Response> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    'X-Request-ID': args.requestId,
  };
  if (args.body !== undefined) headers['Content-Type'] = 'application/json';
  if (args.token) headers.Authorization = `Bearer ${args.token}`;
  if (args.ifMatch) headers['If-Match'] = args.ifMatch;
  if (args.correlationId) headers['X-Correlation-ID'] = args.correlationId;

  const init: RequestInit = {
    method: args.method,
    headers,
    cache: 'no-store',
    credentials: 'include',
  };
  if (args.body !== undefined) init.body = JSON.stringify(args.body);
  return fetch(args.url, init);
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  opts?: V2RequestOptions,
): Promise<T> {
  const url = buildUrl(path);
  const ifMatch = opts?.ifMatch;
  const correlationId = opts?.correlationId;
  const requestId = generateRequestId();
  const tokenOverride = opts && 'token' in opts;

  const initialToken = await resolveToken(opts);

  let res: Response;
  try {
    res = await executeRequest({
      method,
      url,
      body,
      token: initialToken,
      ifMatch,
      requestId,
      correlationId,
    });
  } catch (err) {
    throw new ServiceError('network', (err as Error).message || 'Network error');
  }

  // 401: try the unauthorized handler exactly once. If it returns true we
  // re-resolve the token and replay the request; a second 401 falls through
  // to the normal error path. Skip retry when the caller explicitly pinned a
  // token (tests, edge cases) so we don't fight their intent. The replayed
  // request reuses the same X-Request-ID so the backend can see the auth
  // refresh as part of the same logical attempt.
  if (res.status === 401 && unauthorizedHandler && !tokenOverride) {
    const refreshed = await runV2UnauthorizedHandler();
    if (refreshed) {
      const retryToken = await resolveToken(opts);
      try {
        res = await executeRequest({
          method,
          url,
          body,
          token: retryToken,
          ifMatch,
          requestId,
          correlationId,
        });
      } catch (err) {
        throw new ServiceError('network', (err as Error).message || 'Network error');
      }
    }
  }

  if (!res.ok) {
    const payload = await parseError(res);
    throw toServiceError(payload);
  }

  // 204 No Content
  if (res.status === 204) return undefined as T;
  // Some endpoints (DELETE) return an empty body even on 200.
  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

export const v2Client = {
  get: <T>(path: string, opts?: V2RequestOptions) => request<T>('GET', path, undefined, opts),
  post: <T>(path: string, body?: unknown, opts?: V2RequestOptions) =>
    request<T>('POST', path, body, opts),
  put: <T>(path: string, body?: unknown, opts?: V2RequestOptions) =>
    request<T>('PUT', path, body, opts),
  patch: <T>(path: string, body?: unknown, opts?: V2RequestOptions) =>
    request<T>('PATCH', path, body, opts),
  delete: <T>(path: string, opts?: V2RequestOptions) => request<T>('DELETE', path, undefined, opts),
};
