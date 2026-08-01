import { getSupabaseClientOrNull } from '@/lib/supabase';
import { fetchIntakeSession } from './api';
import type { IntakeSession } from '@/types/intake';

export interface SubscribeOpts {
  sessionId: string;
  onChange: (session: IntakeSession) => void;
  onError?: (err: Error) => void;
  /** Polling fallback interval. Default 1500ms. Pass `null` to disable. */
  pollMs?: number | null;
}

export interface SessionSubscription {
  unsubscribe(): void;
}

const DEFAULT_POLL_MS = 1500;

export function subscribeIntakeSession(opts: SubscribeOpts): SessionSubscription {
  const supabase = getSupabaseClientOrNull();
  let disposed = false;
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  // realtimeUp is load-bearing for the polling-restart-on-channel-error path:
  // it's flipped true on first successful push so polling can stay stopped,
  // and flipped false on CHANNEL_ERROR/TIMED_OUT/CLOSED so polling restarts.
  // Read by startPolling to skip restart when realtime is already healthy.
  let realtimeUp = false;
  let channel: ReturnType<NonNullable<typeof supabase>['channel']> | null = null;

  const pollMs = opts.pollMs === undefined ? DEFAULT_POLL_MS : opts.pollMs;

  // Monotonic run-id so an earlier-started-but-later-resolving refetch can't
  // clobber a fresher one. The poll timer and the realtime-push handler both
  // fire refetch() concurrently; without this, a slow stale response (>pollMs)
  // overwrites newer session state. Mirrors useAsyncList's run-id guard.
  let refetchSeq = 0;

  // Refetch via REST so RLS + org scoping run the same auth path
  // as the initial load — Realtime pushes are intentionally ignored
  // beyond "something changed, re-pull the row".
  async function refetch(): Promise<void> {
    if (disposed) return;
    const mySeq = ++refetchSeq;
    try {
      const row = await fetchIntakeSession(opts.sessionId);
      // Only the latest-issued refetch may apply — drop superseded responses.
      if (!disposed && mySeq === refetchSeq) opts.onChange(row);
    } catch (e) {
      if (!disposed && mySeq === refetchSeq && opts.onError) opts.onError(e as Error);
    }
  }

  function startPolling(): void {
    if (pollTimer !== null || pollMs === null || disposed || realtimeUp) return;
    pollTimer = setInterval(() => {
      void refetch();
    }, pollMs);
  }

  function stopPolling(): void {
    if (pollTimer !== null) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  // Initial fetch — both paths benefit from a fresh row immediately.
  void refetch();

  // Default-on polling until Realtime confirms subscription.
  startPolling();

  if (supabase) {
    const nonce =
      (typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : Math.random().toString(36).slice(2)) as string;
    channel = supabase
      .channel(`intake_sessions:id=eq.${opts.sessionId}:${nonce}`)
      .on(
        // Cast to never because supabase-js v2 types for postgres_changes
        // are sometimes too narrow when the channel arg is a string filter.
        'postgres_changes' as never,
        {
          event: 'UPDATE',
          schema: 'public',
          table: 'intake_sessions',
          filter: `id=eq.${opts.sessionId}`,
        } as never,
        () => {
          realtimeUp = true;
          stopPolling();
          void refetch();
        },
      )
      .subscribe((status) => {
        if (status === 'SUBSCRIBED') {
          // Connected — let Realtime drive; polling stops on first push.
          // If no push for 5s the polling stays a safety net.
          return;
        }
        if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT' || status === 'CLOSED') {
          realtimeUp = false;
          startPolling();
        }
      });
  }

  return {
    unsubscribe(): void {
      disposed = true;
      stopPolling();
      if (channel && supabase) supabase.removeChannel(channel);
      realtimeUp = false;
    },
  };
}
