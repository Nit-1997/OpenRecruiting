import { expect } from 'bun:test';
import type * as IntakeApi from '../api';

// Test helpers for the api.*.test.ts files, which exercise the GENUINE
// `@/lib/intake/api` module while other test files mock it process-wide.
//
// Two bun realities drive this file:
//
// 1. `mock.module` MUTATES the target module's namespace object in place, is
//    process-wide, last-writer-wins, and bun loads every file's top-level
//    `mock.module(...)` BEFORE running any test. Several hooks/component tests
//    stub api functions (two replace the whole module). A plain
//    `import { switchModality } from '../api'` here would therefore resolve to a
//    stub or `undefined` (making `for await (streamTextTurn())` hang to 5s and
//    `await switchModality()` return `undefined`). `realIntakeApi()` returns a
//    DETACHED snapshot of the genuine exports captured in src/test-setup.ts at
//    preload, so we always call the real functions.
//
// 2. Mocking a module DECOUPLES its internal lexical bindings — even when the
//    function under test is itself real, a class DEFINED inside the module
//    (IntakeApiError, ModalityConflictError) that the function `throw`s is no
//    longer reference-equal to the snapshot's class once any other file has
//    mocked the module. (Classes IMPORTED from another, un-mocked module —
//    ReprocessAlreadyRunningError, VoiceDrainFailedError from @/types/intake —
//    are unaffected, so `instanceof` still works for those.) We therefore assert
//    the SHAPE of the api-defined errors instead of `instanceof`. Verified
//    minimal repro: a `mock.module(spec, () => ({ ...actual, other: () => {} }))`
//    in one file makes a real `throw new InternalClass()` in another file fail
//    `instanceof InternalClass`.

export function realIntakeApi(): typeof IntakeApi {
  const real = (globalThis as { __REAL_INTAKE_API__?: typeof IntakeApi }).__REAL_INTAKE_API__;
  if (!real) {
    throw new Error(
      'realIntakeApi(): snapshot missing — src/test-setup.ts must run as a bun test preload.',
    );
  }
  return real;
}

// Genuine `@/lib/intake/realtime` module. Two hooks tests replace that module
// with a `subscribeIntakeSession` stub process-wide, so realtime.test.ts would
// otherwise drive the stub instead of the real subscribe path.
export function realIntakeRealtime(): typeof import('../realtime') {
  const real = (globalThis as { __REAL_INTAKE_REALTIME__?: typeof import('../realtime') })
    .__REAL_INTAKE_REALTIME__;
  if (!real) {
    throw new Error(
      'realIntakeRealtime(): snapshot missing — src/test-setup.ts must run as a bun test preload.',
    );
  }
  return real;
}

// Genuine `@/lib/v2-client` module. Five service/store test files replace it
// process-wide with stubs whose setV2TokenGetter/setV2UnauthorizedHandler are
// no-ops, which would make the FE-F4 401-refresh tests silently register
// nothing. The genuine api.ts calls the REAL resolveV2Token/
// runV2UnauthorizedHandler, so those tests must register handlers via the REAL
// setters captured here at preload.
export function realV2Client(): typeof import('@/lib/v2-client') {
  const real = (globalThis as { __REAL_V2_CLIENT__?: typeof import('@/lib/v2-client') })
    .__REAL_V2_CLIENT__;
  if (!real) {
    throw new Error(
      'realV2Client(): snapshot missing — src/test-setup.ts must run as a bun test preload.',
    );
  }
  return real;
}

interface ApiErrorLike {
  name: string;
  status: number;
  detail: string;
  code?: string;
}

function asApiErrorLike(err: unknown): ApiErrorLike {
  const e = err as Partial<ApiErrorLike> | undefined;
  if (
    !e ||
    e.name !== 'IntakeApiError' ||
    typeof e.status !== 'number' ||
    typeof e.detail !== 'string'
  ) {
    throw new Error(
      `expected an IntakeApiError, got ${err instanceof Error ? `${err.name}: ${err.message}` : String(err)}`,
    );
  }
  return e as ApiErrorLike;
}

// Identity-independent assertion for an IntakeApiError (see note 2 above).
export function expectIntakeApiError(
  err: unknown,
  match?: { status?: number; code?: string; detail?: string | RegExp },
): ApiErrorLike {
  const e = asApiErrorLike(err);
  if (match?.status !== undefined) expect(e.status).toBe(match.status);
  if (match?.code !== undefined) expect(e.code).toBe(match.code);
  if (match?.detail !== undefined) {
    if (match.detail instanceof RegExp) expect(e.detail).toMatch(match.detail);
    else expect(e.detail).toContain(match.detail);
  }
  return e;
}

// Identity-independent assertion for a ModalityConflictError (a subclass of
// IntakeApiError defined inside api.ts — see note 2 above).
export function expectModalityConflictError(
  err: unknown,
  match?: { held?: string; requested?: string },
): void {
  const e = err as { name?: string; code?: string; held?: string; requested?: string } | undefined;
  if (!e || e.name !== 'ModalityConflictError' || e.code !== 'modality_conflict') {
    throw new Error(
      `expected a ModalityConflictError, got ${err instanceof Error ? `${err.name}: ${err.message}` : String(err)}`,
    );
  }
  if (match?.held !== undefined) expect(e.held).toBe(match.held);
  if (match?.requested !== undefined) expect(e.requested).toBe(match.requested);
}
