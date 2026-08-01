'use client';

import { useContext, useEffect, useState } from 'react';
import { IntakeSessionContext } from '@/components/sub-agents/intake/IntakeSessionProvider';
import { subscribeIntakeSession } from '@/lib/intake/realtime';
import type { IntakeSession } from '@/types/intake';

interface State {
  session: IntakeSession | null;
  isLoading: boolean;
  error: Error | null;
}

export function useIntakeSession(sessionId: string | null): State {
  // Prefer the hoisted provider subscription when it already serves THIS session
  // id — that keeps the whole intake tree on a single Realtime channel + poll.
  const ctx = useContext(IntakeSessionContext);
  const servedByProvider = ctx !== null && ctx.sessionId === sessionId;

  const [session, setSession] = useState<IntakeSession | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(sessionId !== null);
  const [error, setError] = useState<Error | null>(null);

  // Only open a private subscription when the provider does NOT cover this id
  // (different session, or no provider at all). Re-runs if either changes.
  useEffect(() => {
    if (servedByProvider) return;
    if (!sessionId) {
      setSession(null);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    const sub = subscribeIntakeSession({
      sessionId,
      onChange: (s) => {
        setSession(s);
        setIsLoading(false);
        setError(null);
      },
      onError: (e) => {
        setError(e);
        setIsLoading(false);
      },
      // Use default 1.5s polling fallback per spec §6.3.
    });
    return () => sub.unsubscribe();
  }, [sessionId, servedByProvider]);

  if (servedByProvider) {
    return { session: ctx.session, isLoading: ctx.isLoading, error: ctx.error };
  }
  return { session, isLoading, error };
}
