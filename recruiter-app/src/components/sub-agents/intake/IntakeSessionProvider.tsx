'use client';

import { createContext, type ReactNode, useEffect, useState } from 'react';
import { subscribeIntakeSession } from '@/lib/intake/realtime';
import type { IntakeSession } from '@/types/intake';

export interface IntakeSessionContextValue {
  sessionId: string | null;
  session: IntakeSession | null;
  isLoading: boolean;
  error: Error | null;
}

// Holds the ONE shared subscription for the active intake session. Before this,
// canvas + prefill-diff-panel + use-process-till-now each instantiated their own
// useIntakeSession(sessionId), opening 3 Realtime channels + 3×1.5s polls for the
// same row. Consumers now read this context (via useIntakeSession) and only fall
// back to a private subscription when used for a DIFFERENT session id or outside
// any provider.
export const IntakeSessionContext = createContext<IntakeSessionContextValue | null>(null);

export function IntakeSessionProvider({
  sessionId,
  children,
}: {
  sessionId: string | null;
  children: ReactNode;
}) {
  const [session, setSession] = useState<IntakeSession | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(sessionId !== null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!sessionId) {
      setSession(null);
      setIsLoading(false);
      setError(null);
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
    });
    return () => sub.unsubscribe();
  }, [sessionId]);

  return (
    <IntakeSessionContext.Provider value={{ sessionId, session, isLoading, error }}>
      {children}
    </IntakeSessionContext.Provider>
  );
}
