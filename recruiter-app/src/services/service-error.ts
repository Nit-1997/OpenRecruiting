export type ServiceErrorCode =
  | 'not_found'
  | 'conflict'
  | 'validation'
  | 'forbidden'
  | 'invalid_state'
  | 'network'
  | 'internal';

const DEFAULT_STATUS: Record<ServiceErrorCode, number> = {
  not_found: 404,
  conflict: 409,
  validation: 422,
  forbidden: 403,
  invalid_state: 409,
  network: 503,
  internal: 500,
};

export interface ServiceErrorOptions {
  httpStatus?: number;
  field?: string;
  /** X-Request-ID echoed by the v2 backend; surfaced here so error
   *  toasts / logs can carry it for triage. */
  requestId?: string;
  /** Raw backend `detail` string (e.g. "RPC error: 42704 ..."). Carried
   *  on the error for logging / Sentry-style capture, but never shown
   *  directly to the user — `message` is the user-facing copy. */
  rawDetail?: string;
}

export class ServiceError extends Error {
  readonly code: ServiceErrorCode;
  readonly httpStatus: number;
  readonly field?: string;
  readonly requestId?: string;
  readonly rawDetail?: string;

  constructor(code: ServiceErrorCode, message: string, opts: ServiceErrorOptions = {}) {
    super(message);
    this.name = 'ServiceError';
    this.code = code;
    this.httpStatus = opts.httpStatus ?? DEFAULT_STATUS[code];
    if (opts.field !== undefined) this.field = opts.field;
    if (opts.requestId !== undefined) this.requestId = opts.requestId;
    if (opts.rawDetail !== undefined) this.rawDetail = opts.rawDetail;
  }
}

/**
 * Typed error for a service method that has NO real `/api/v2/*` endpoint yet
 * but is invoked while the v2 API is enabled (production default). The mock
 * fallback would otherwise fabricate localStorage data indistinguishable from
 * real data — a data-integrity hazard. We fail loudly instead so the UI can
 * surface "not available yet" rather than silently showing fake data.
 *
 * Uses `code: 'not_found'` so existing UI toast handling (keyed on
 * `ServiceErrorCode`) renders it as an absence rather than a crash. The
 * stable `rawDetail` prefix (`NOT_IMPLEMENTED_IN_V2:`) is greppable for
 * triage and lets call sites detect this specific case if they need to.
 */
export function notImplementedInV2(methodName: string): ServiceError {
  return new ServiceError('not_found', 'This feature is not available yet.', {
    rawDetail: `NOT_IMPLEMENTED_IN_V2: ${methodName}`,
  });
}
