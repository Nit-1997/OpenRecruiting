'use client';

import { useCallback, useEffect, useState } from 'react';
import { listIntakeSessions } from '@/lib/intake/api';
import type { SessionListItem } from '@/types/intake';

interface State {
  sessions: SessionListItem[];
  isLoading: boolean;
  error: Error | null;
  refetch: () => Promise<void>;
}

export function useIntakeSessionsList(): State {
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const r = await listIntakeSessions();
      setSessions(r.sessions);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return { sessions, isLoading, error, refetch: load };
}
