import { afterEach, beforeEach, mock } from 'bun:test';
import { GlobalRegistrator } from '@happy-dom/global-registrator';

// Opt OUT of v2 API in unit tests — the legacy mock-db tests drive code
// against the in-memory seed and would otherwise try to make HTTP calls
// to a backend that isn't running. Production code is unaffected (the
// default in `src/lib/env.ts` stays v2-on).
//
// IMPORTANT: bun runs test FILES concurrently within one process. Any
// file that mutates `process.env.NEXT_PUBLIC_V2_API` at module top-level
// (v2-wiring.test.ts, auth-store.test.ts) races with files that depend
// on the default 'false' mode. Setting this in `beforeEach` ensures every
// test starts from a clean baseline regardless of what other files did
// in their top-level scope. Individual tests that need v2-on can flip
// the var inside their own block.
process.env.NEXT_PUBLIC_V2_API = 'false';
beforeEach(() => {
  process.env.NEXT_PUBLIC_V2_API = 'false';
});

GlobalRegistrator.register();

// Cross-file fetch isolation.
//
// `globalThis.fetch` is process-global and bun shares one process across all
// test files. A file that sets `globalThis.fetch = someMock` and forgets to
// restore it — or whose own async work is still in-flight when the next file's
// test runs — leaks that mock. The victim then sees an alien mock (frequently a
// one-shot `mockResolvedValueOnce` already consumed, or a never-resolving
// promise) and fails or hangs in ways that never reproduce in isolation.
//
// We capture the pristine `fetch` once at preload and restore it after EVERY
// test, so no file can carry a mutated `fetch` past its own test boundary.
// Per-file `afterEach` restores still run first (afterEach is LIFO); this is the
// backstop for files that forget one.
const PRISTINE_FETCH = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = PRISTINE_FETCH;
});

// Cross-file module-mock isolation for `@/lib/intake/api` (+ realtime).
//
// bun LOADS every test file's top-level code (including every `mock.module(...)`
// call) BEFORE running any test, and `mock.module` is process-wide & last-writer-
// wins. Several hooks/component tests stub one api function via `{ ...actual, X:
// mock() }`. At test time the genuine api.*.test.ts files would therefore import
// a stub for the unit under test (a bare `mock()` returns `undefined`, so
// `await switchModality()` yields `undefined` and `for await (streamTextTurn())`
// hangs to the 5s timeout).
//
// We snapshot the GENUINE module here at preload — this runs before any test file
// loads, so `require` returns the real exports — into a DETACHED object (copied
// key-by-key, because `mock.module` MUTATES the live namespace object in place,
// so a live reference would later turn into a leaker's stub). The api.*.test.ts
// files read this snapshot via `realIntakeApi()` / `realIntakeRealtime()` (see
// src/lib/intake/__tests__/restore-real-api.ts) so they always call the genuine
// implementation regardless of what other files mocked. Leaker files keep their
// own per-file mocks untouched.
function snapshotModule(id: string): Record<string, unknown> {
  const live = require(id) as Record<string, unknown>;
  const snapshot: Record<string, unknown> = {};
  for (const key of Object.keys(live)) snapshot[key] = live[key];
  return snapshot;
}

(globalThis as { __REAL_INTAKE_API__?: unknown }).__REAL_INTAKE_API__ =
  snapshotModule('@/lib/intake/api');
// realtime.ts is itself mocked by two hooks tests — snapshot it too so
// realtime.test.ts can drive the genuine subscribe path.
(globalThis as { __REAL_INTAKE_REALTIME__?: unknown }).__REAL_INTAKE_REALTIME__ =
  snapshotModule('@/lib/intake/realtime');
// v2-client.ts is mocked process-wide by 5 service/store test files (each
// replaces it with a stub that omits setV2TokenGetter/setV2UnauthorizedHandler
// or makes them no-ops). The genuine api.ts internally calls the REAL
// resolveV2Token/runV2UnauthorizedHandler (its static bindings were resolved at
// preload), so the FE-F4 401-refresh tests must register handlers via the REAL
// setters — not a leaker's no-op stub. Snapshot them here.
(globalThis as { __REAL_V2_CLIENT__?: unknown }).__REAL_V2_CLIENT__ =
  snapshotModule('@/lib/v2-client');

// plan-tab.tsx is mocked process-wide by role-detail-page.test.tsx (it replaces
// PlanTab with a `<div data-testid="plan-tab" />` stub). plan-tab.test.tsx needs
// the GENUINE component to drive its inline editors/confirm dialog. Snapshot the
// real module here at preload so it can read the real PlanTab via this global
// regardless of which file's mock won the registry.
(globalThis as { __REAL_PLAN_TAB__?: unknown }).__REAL_PLAN_TAB__ = snapshotModule(
  '@/components/role-detail/plan-tab',
);

// debrief-tab.tsx is mocked process-wide by role-detail-page.test.tsx (it stubs
// `DebriefTab`). debrief-tab.test.tsx needs the GENUINE `PacketCard` export.
// Snapshot the real module at preload so it can read the real exports
// regardless of which file's mock won the registry (mirrors __REAL_PLAN_TAB__).
(globalThis as { __REAL_DEBRIEF_TAB__?: unknown }).__REAL_DEBRIEF_TAB__ = snapshotModule(
  '@/components/role-detail/debrief-tab',
);

// Cross-file SWR cache isolation.
//
// `useAsyncList`'s module-level `__asyncCache` (see use-services.ts) is
// process-global and survives across test files. A file that renders a component
// through the REAL data hooks (e.g. drawer.loaded seeds `packet:*` keys) would
// otherwise warm-seed a LATER file's hooks, painting cached data where that file
// expects a cold/empty state. Clear it after every test so each test starts from
// an empty cache. We `require` (not a top-level import) so it runs AFTER the env
// baseline set above, matching the snapshot pattern in this file.
const { clearAsyncCache: _clearAsyncCache } = require('@/hooks/use-services') as {
  clearAsyncCache: () => void;
};
afterEach(() => {
  _clearAsyncCache();
});

const routerStub = {
  push: () => {},
  replace: () => {},
  back: () => {},
  forward: () => {},
  refresh: () => {},
  prefetch: () => {},
};

const searchParamsStub = new URLSearchParams();

mock.module('next/navigation', () => ({
  useRouter: () => routerStub,
  usePathname: () => '/',
  useSearchParams: () => searchParamsStub,
  useParams: () => ({}),
  useSelectedLayoutSegment: () => null,
  useSelectedLayoutSegments: () => [],
  redirect: () => {},
  notFound: () => {},
}));

afterEach(() => {
  document.body.innerHTML = '';
});
