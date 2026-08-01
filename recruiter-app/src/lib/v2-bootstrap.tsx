'use client';

// Client-side bootstrap that wires the auth-store + supabase-js into the v2
// HTTP client.
//
// Mounted once at the top of the root layout. The side-effect block at module
// scope installs the bearer-token getter and the 401 retry hook so any v2
// service call made during the first React render already sees them. The
// component itself then triggers `loadFromStorage()` and `bindAuthListener()`
// on mount.

import { useEffect } from 'react';
import { isV2ApiEnabled } from '@/lib/env';
import { getSupabaseClientOrNull } from '@/lib/supabase';
import { setV2TokenGetter, setV2UnauthorizedHandler } from '@/lib/v2-client';
import { useAuthStore } from '@/stores/auth-store';

// Re-entrancy guard: if multiple v2 calls race on a single 401, fan them all
// into a single refresh attempt rather than spamming supabase.
let inflightRefresh: Promise<boolean> | null = null;

async function refreshOnce(): Promise<boolean> {
  if (!inflightRefresh) {
    inflightRefresh = (async () => {
      const supabase = getSupabaseClientOrNull();
      if (!supabase) return false;
      const { data, error } = await supabase.auth.refreshSession();
      if (error || !data.session) {
        // Refresh failed — clear the store so the UI can redirect to /login.
        await useAuthStore.getState().signOut();
        return false;
      }
      return true;
    })().finally(() => {
      inflightRefresh = null;
    });
  }
  return inflightRefresh;
}

// Side-effect: install the token getter. supabase-js auto-refreshes the token
// before expiry, so calling `getSession()` here always returns a fresh-enough
// token — no manual expiry-skew math required.
setV2TokenGetter(async () => {
  if (!isV2ApiEnabled()) {
    // Mock mode: surface the mock access token so service-mode code that
    // gates on Authorization (rare) still observes a non-null bearer.
    return useAuthStore.getState().session?.access_token ?? null;
  }
  const supabase = getSupabaseClientOrNull();
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
});

// Side-effect: install the 401 retry hook. Returns true if the refresh
// succeeded so v2-client replays the original request; false otherwise.
setV2UnauthorizedHandler(async () => {
  if (!isV2ApiEnabled()) return false;
  return refreshOnce();
});

// Side-effect: hydrate persisted supabase session on the first browser-side
// import. Gated on `window` because Next.js evaluates client modules during
// SSR for server components too.
let storageLoaded = false;
function loadOnce(): void {
  if (storageLoaded) return;
  if (typeof window === 'undefined') return;
  storageLoaded = true;
  void useAuthStore.getState().loadFromStorage();
}

export function V2Bootstrap(): null {
  // Hydrate and bind the supabase auth listener on mount. `bindAuthListener`
  // returns its own unsubscribe so external session changes (TOKEN_REFRESHED,
  // SIGNED_OUT) propagate into the store for as long as the app is mounted.
  useEffect(() => {
    loadOnce();
    const unsubscribe = useAuthStore.getState().bindAuthListener();
    return () => {
      unsubscribe();
    };
  }, []);
  return null;
}
