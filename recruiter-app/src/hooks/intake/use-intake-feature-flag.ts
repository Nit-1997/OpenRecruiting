'use client';

import { useEffect, useState } from 'react';
import { fetchIntakeFeatureFlag } from '@/lib/intake/api';

interface State {
  enabled: boolean;
  isLoading: boolean;
}

// Uses Bearer auth via lib/intake/api.ts (which attaches the supabase-js
// session access_token automatically). Mirrors the fix in recruiter-app/
// commit 5ad3b00: feature-flag fetch MUST go through the Bearer-auth path
// or it 401s and the entry hides for everyone.
export function useIntakeFeatureFlag(): State {
  const [state, setState] = useState<State>({ enabled: false, isLoading: true });

  useEffect(() => {
    let cancelled = false;
    void fetchIntakeFeatureFlag()
      .then((b) => {
        if (!cancelled) setState({ enabled: Boolean(b.intake_v2_enabled), isLoading: false });
      })
      .catch(() => {
        // Any error (network, 403, 500) collapses to "not enabled" — better
        // to hide the entry than show a broken intake.
        if (!cancelled) setState({ enabled: false, isLoading: false });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
