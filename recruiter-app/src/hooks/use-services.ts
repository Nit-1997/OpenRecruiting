'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  ActivityEvent,
  BillingOverview,
  Candidate,
  CandidateRound,
  Debrief,
  DebriefInsight,
  FeedbackEntry,
  Integration,
  NotificationPreferences,
  Profile,
  Requisition,
  RoundRecording,
  TeamOverview,
} from '@/domain';
import {
  emitServiceEvent as _emit,
  activity,
  billing,
  candidates as candidateSvc,
  debrief as debriefSvc,
  feedback,
  integrations,
  onServiceEvent,
  profile,
  requisitions,
  team,
  untracked,
} from '@/services';
import type { CandidatePacket } from '@/services/candidates';
import type { ServiceEventName } from '@/services/events';
import type {
  ListRolesOptions,
  RequisitionStatusFilter,
  RoleListPage,
} from '@/services/requisitions';
import type { ListUntrackedOptions, UntrackedListPage } from '@/services/untracked';

// ── Stale-while-revalidate cache ───────────────────────────────────────────
// Keyed per-query (see each wrapper hook's cacheKey). A warm remount paints the
// last value instantly while a background revalidation runs. Cleared on logout
// (clearAsyncCache, called from auth-store.signOut) so a prior user's data can
// never paint for the next user on a shared device. Exported `__asyncCache` is
// for tests only.
export const __asyncCache = new Map<string, { data: unknown }>();

export function clearAsyncCache(): void {
  __asyncCache.clear();
}

/**
 * No-op. Kept as a hook so every existing call site continues to compile
 * without churn. Seeding is NOT done here: in production (v2 enabled) the
 * mock seed is never registered at all, and in the opt-out test/demo path
 * (NEXT_PUBLIC_V2_API=false) AppShell registers the seed factory once via
 * `registerSeedFactory()` and `mock-db.getDb()` lazy-seeds on first access.
 * Drop calls to this hook over time.
 *
 * @deprecated
 */
export function useEnsureSeeded(): void {
  // Intentionally empty.
}

interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: Error | null;
  refetch: () => void;
}

/**
 * Loader signature accepts an optional `AbortSignal`. Loaders that support
 * cancellation should forward it to the underlying request; loaders that don't
 * may ignore it — the run-id guard below still prevents stale paint.
 */
type AsyncLoader<T> = (signal?: AbortSignal) => Promise<T>;

export function useAsyncList<T>(
  loader: AsyncLoader<T>,
  events: ServiceEventName[],
  deps: readonly unknown[] = [],
  options?: { cacheKey?: string },
): AsyncState<T> {
  const cacheKey = options?.cacheKey;
  const cacheKeyRef = useRef(cacheKey);
  cacheKeyRef.current = cacheKey;

  // Warm mount: seed from cache so the view paints last-known data immediately
  // (loading stays true — a background revalidation runs below).
  const [state, setState] = useState<{ data: T | null; loading: boolean; error: Error | null }>(
    () => {
      const cached = cacheKey ? __asyncCache.get(cacheKey) : undefined;
      if (cached) {
        return { data: cached.data as T, loading: true, error: null };
      }
      return { data: null, loading: true, error: null };
    },
  );
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const runIdRef = useRef(0);
  const inFlightRef = useRef<AbortController | null>(null);

  const reload = useCallback(() => {
    const myRun = ++runIdRef.current;
    inFlightRef.current?.abort();
    const ctrl = new AbortController();
    inFlightRef.current = ctrl;

    setState((s) => ({ ...s, loading: true }));
    loaderRef
      .current(ctrl.signal)
      .then((data) => {
        const key = cacheKeyRef.current;
        if (key) __asyncCache.set(key, { data });
        if (runIdRef.current === myRun) {
          setState({ data, loading: false, error: null });
        }
      })
      .catch((error) => {
        if (runIdRef.current === myRun && !ctrl.signal.aborted) {
          // Keep stale data if we have any (revalidate failure); only surface an
          // error when there is nothing cached to show.
          setState((s) =>
            s.data != null
              ? { ...s, loading: false }
              : { data: null, loading: false, error: error as Error },
          );
        }
      });
  }, []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: deps control reload
  useEffect(() => {
    reload();
    const offs = events.map((e) =>
      onServiceEvent(e, () => {
        reload();
      }),
    );
    return () => {
      offs.forEach((off) => {
        off();
      });
      runIdRef.current += 1;
      inFlightRef.current?.abort();
      inFlightRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reload, ...deps]);
  return { ...state, refetch: reload };
}

// Roles rail: one paginated request per tab with the canonical status
// filter. Each response carries `status_counts` (org-wide) and per-item
// `pipeline` counts so the rail renders without N+1 fetches per row.
//
// Pagination is per-tab: changing tab or page refires the request. The
// hook deps are flattened so callers can pass `{ page, page_size }`
// without forcing identity equality across renders.
export function useRequisitions(
  status?: RequisitionStatusFilter,
  options?: ListRolesOptions,
): AsyncState<RoleListPage> {
  useEnsureSeeded();
  const page = options?.page ?? 1;
  const pageSize = options?.page_size ?? 10;
  // `q` is applied server-side so the rail search works across all pages.
  // Empty/whitespace strings are treated as no-search (handled by services).
  const q = options?.q;
  return useAsyncList<RoleListPage>(
    () => requisitions.list(status, { page, page_size: pageSize, q }),
    [
      'requisition:created',
      'requisition:updated',
      'requisition:status_changed',
      'requisition:deleted',
    ],
    [status, page, pageSize, q],
    { cacheKey: `roles:list:${status ?? 'all'}:${page}:${pageSize}:${q ?? ''}` },
  );
}

export function useRequisition(id: string | null | undefined): AsyncState<Requisition> {
  useEnsureSeeded();
  return useAsyncList<Requisition>(
    () => {
      if (!id) return Promise.reject(new Error('No requisition id'));
      return requisitions.get(id);
    },
    [
      'requisition:updated',
      'requisition:status_changed',
      'round:created',
      'round:updated',
      'round:deleted',
      'round:reordered',
      'question:created',
      'question:updated',
      'question:deleted',
    ],
    [id],
    { cacheKey: `role:${id ?? 'none'}` },
  );
}

export function useCandidatesForRequisition(
  reqId: string | null | undefined,
): AsyncState<Candidate[]> {
  useEnsureSeeded();
  return useAsyncList<Candidate[]>(
    () => {
      if (!reqId) return Promise.resolve([]);
      return candidateSvc.listForReq(reqId);
    },
    // Spec §7: pipeline candidates carry their candidate_rounds nested.
    // Refetch on CR + plan-shape changes so the rail stays in sync without
    // each row firing its own listRounds call (N+1 anti-pattern).
    [
      'candidate:created',
      'candidate:updated',
      'candidate:deleted',
      'candidate:status_changed',
      'candidate_round:updated',
      'feedback:submitted',
      'round:created',
      'round:updated',
      'round:deleted',
      'round:reordered',
    ],
    [reqId],
    { cacheKey: `pipeline-cands:${reqId ?? 'none'}` },
  );
}

export function useCandidateRounds(
  reqId: string | null | undefined,
  candidateId: string | null | undefined,
): AsyncState<CandidateRound[]> {
  useEnsureSeeded();
  return useAsyncList<CandidateRound[]>(
    () => {
      if (!reqId || !candidateId) return Promise.resolve([]);
      return candidateSvc.listRounds(reqId, candidateId);
    },
    [
      'candidate_round:updated',
      'feedback:submitted',
      'round:created',
      'round:deleted',
      'round:reordered',
    ],
    [reqId, candidateId],
    { cacheKey: `cand-rounds:${reqId ?? 'none'}:${candidateId ?? 'none'}` },
  );
}

export function useRoundFeedback(
  reqId: string | null | undefined,
  candidateId: string | null | undefined,
  roundId: string | null | undefined,
): AsyncState<FeedbackEntry[]> {
  useEnsureSeeded();
  return useAsyncList<FeedbackEntry[]>(
    () => {
      if (!reqId || !candidateId || !roundId) return Promise.resolve([]);
      return feedback.getRoundFeedback(reqId, candidateId, roundId);
    },
    ['feedback:submitted'],
    [reqId, candidateId, roundId],
    { cacheKey: `round-feedback:${reqId ?? 'none'}:${candidateId ?? 'none'}:${roundId ?? 'none'}` },
  );
}

export function useRecording(
  candidateRoundId: string | null | undefined,
): AsyncState<RoundRecording | null> {
  useEnsureSeeded();
  return useAsyncList<RoundRecording | null>(
    () => {
      if (!candidateRoundId) return Promise.resolve(null);
      return feedback.getRecording(candidateRoundId);
    },
    ['candidate_round:updated', 'feedback:submitted'],
    [candidateRoundId],
    { cacheKey: `recording:${candidateRoundId ?? 'none'}` },
  );
}

export function useDebrief(reqId: string | null | undefined): AsyncState<Debrief> {
  useEnsureSeeded();
  return useAsyncList<Debrief>(
    () => {
      if (!reqId) return Promise.reject(new Error('No requisition id'));
      return debriefSvc.get(reqId);
    },
    ['feedback:submitted', 'candidate:status_changed'],
    [reqId],
    { cacheKey: `debrief:${reqId ?? 'none'}` },
  );
}

export function useDebriefInsights(reqId: string | null | undefined): AsyncState<DebriefInsight> {
  useEnsureSeeded();
  return useAsyncList<DebriefInsight>(
    () => {
      if (!reqId) return Promise.reject(new Error('No requisition id'));
      return debriefSvc.getInsights(reqId);
    },
    ['feedback:submitted', 'candidate:status_changed'],
    [reqId],
    { cacheKey: `debrief-insights:${reqId ?? 'none'}` },
  );
}

export function useTeam(): AsyncState<TeamOverview> {
  useEnsureSeeded();
  return useAsyncList<TeamOverview>(() => team.get(), ['team:updated'], [], {
    cacheKey: 'team',
  });
}

export function useBillingOverview(): AsyncState<BillingOverview> {
  useEnsureSeeded();
  return useAsyncList<BillingOverview>(() => billing.getOverview(), ['billing:updated'], [], {
    cacheKey: 'billing',
  });
}

export function useIntegrations(): AsyncState<Integration[]> {
  useEnsureSeeded();
  return useAsyncList<Integration[]>(() => integrations.list(), ['integration:updated'], [], {
    cacheKey: 'integrations',
  });
}

export function useProfile(): AsyncState<Profile> {
  useEnsureSeeded();
  return useAsyncList<Profile>(() => profile.get(), ['profile:updated'], [], {
    cacheKey: 'profile',
  });
}

export function useNotificationPrefs(): AsyncState<NotificationPreferences> {
  useEnsureSeeded();
  return useAsyncList<NotificationPreferences>(
    () => profile.getNotificationPrefs(),
    ['notification_prefs:updated'],
    [],
    { cacheKey: 'notification-prefs' },
  );
}

export function useActivity(limit = 20): AsyncState<ActivityEvent[]> {
  useEnsureSeeded();
  return useAsyncList<ActivityEvent[]>(() => activity.list(limit), ['activity:created'], [limit], {
    cacheKey: `activity:${limit}`,
  });
}

export function useUntracked(options?: ListUntrackedOptions): AsyncState<UntrackedListPage> {
  useEnsureSeeded();
  const page = options?.page ?? 1;
  const pageSize = options?.page_size ?? 10;
  return useAsyncList<UntrackedListPage>(
    () => untracked.list({ page, page_size: pageSize }),
    ['untracked:updated'],
    [page, pageSize],
    { cacheKey: `untracked:${page}:${pageSize}` },
  );
}

/**
 * Fetch the rich feedback packet for an untracked interview. Calls the
 * dedicated v2 endpoint (which the standard packet RPC can't serve for
 * materialized-untracked rows) and shapes the result into the same
 * `CandidatePacket` the PacketDrawer expects.
 */
export function useUntrackedPacket(
  untrackedId: string | null | undefined,
): AsyncState<CandidatePacket | null> {
  useEnsureSeeded();
  return useAsyncList<CandidatePacket | null>(
    () => {
      if (!untrackedId) return Promise.resolve(null);
      return untracked.getPacket(untrackedId);
    },
    ['untracked:updated', 'candidate_round:updated', 'feedback:submitted'],
    [untrackedId],
    { cacheKey: `untracked-packet:${untrackedId ?? 'none'}` },
  );
}

// Spec §7: the packet drawer fires ONE call to /roles/{id}/candidates/{cid}/packet
// at mount. All drawer reads (candidate rounds, per-round feedback, recording
// metadata) derive from this single response.
export function usePacket(
  reqId: string | null | undefined,
  candidateId: string | null | undefined,
): AsyncState<CandidatePacket | null> {
  useEnsureSeeded();
  return useAsyncList<CandidatePacket | null>(
    () => {
      if (!reqId || !candidateId) return Promise.resolve(null);
      return candidateSvc.getPacket(reqId, candidateId);
    },
    [
      'candidate_round:updated',
      'feedback:submitted',
      'feedback:requested',
      'round:created',
      'round:deleted',
      'round:reordered',
    ],
    [reqId, candidateId],
    { cacheKey: `packet:${reqId ?? 'none'}:${candidateId ?? 'none'}` },
  );
}
