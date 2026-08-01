import type { Session as SupabaseSession } from '@supabase/supabase-js';
import { create } from 'zustand';
import { clearAsyncCache } from '@/hooks/use-services';
import { isV2ApiEnabled } from '@/lib/env';
import { getSupabaseClient } from '@/lib/supabase';
import { v2Client } from '@/lib/v2-client';
import { emit } from '@/services/events';
import * as teamSvc from '@/services/team';

// Legacy demo credentials — still re-exported for any code that pinned to them
// (login fixtures, e2e helpers). Real auth no longer cares about these values.
export const DEMO_EMAIL = 'demo@example.com';
export const DEMO_PASSWORD = 'demo1234';

export type AuthStatus = 'idle' | 'authenticating' | 'authenticated' | 'unauthenticated';

export interface AuthSession {
  access_token: string;
  refresh_token: string;
  expires_at: number; // unix seconds
  user: { id: string; email: string };
}

export interface AuthProfile {
  id: string;
  email: string;
  organization_id: string | null;
  is_staff: boolean;
  name: string | null;
  has_pending_invite: boolean;
}

interface AuthStateData {
  session: AuthSession | null;
  profile: AuthProfile | null;
  status: AuthStatus;
  error: string | null;
  // Mirror of `status === 'authenticated'`. Kept as a real field (not a
  // getter) so Zustand's shallow merges preserve it and selector subscribers
  // re-render on transitions.
  authed: boolean;
  // False until the FIRST session check (loadFromStorage / auth listener) has
  // resolved. Auth gates MUST wait for this before redirecting — otherwise they
  // act on the initial `unauthenticated` placeholder and bounce an authed user
  // to the login app mid-hydration (infinite redirect loop with landing).
  initialized: boolean;
}

interface AuthStateActions {
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  loadFromStorage: () => Promise<void>;
  fetchProfile: () => Promise<void>;
  // Subscribes to supabase-js auth state changes (TOKEN_REFRESHED, SIGNED_OUT,
  // etc.) so external session transitions propagate into this store without
  // manual polling. Returns an unsubscribe function. Called once at bootstrap.
  bindAuthListener: () => () => void;
}

type AuthState = AuthStateData & AuthStateActions;

const MOCK_SESSION: AuthSession = {
  access_token: 'mock-access-token',
  refresh_token: 'mock-refresh-token',
  expires_at: Math.floor(Date.now() / 1000) + 60 * 60 * 24 * 365, // a year out
  user: { id: 'mock-user', email: DEMO_EMAIL },
};

const MOCK_PROFILE: AuthProfile = {
  id: 'mock-user',
  email: DEMO_EMAIL,
  organization_id: 'mock-org',
  is_staff: false,
  name: 'Demo Recruiter',
  has_pending_invite: false,
};

const PLACEHOLDER_PROFILE_NO_ORG: Omit<AuthProfile, 'id' | 'email'> = {
  organization_id: null,
  is_staff: false,
  name: null,
  has_pending_invite: false,
};

// One-time wipe of the old persisted-session key from the pre-supabase-js
// implementation. Supabase-js now owns auth storage under a different key.
const LEGACY_STORAGE_KEY = 'openrecruiting.auth.v2';

function clearLegacyStorage(): void {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.removeItem(LEGACY_STORAGE_KEY);
  } catch {
    // ignored
  }
}

function mapSupabaseSession(s: SupabaseSession): AuthSession {
  return {
    access_token: s.access_token,
    refresh_token: s.refresh_token,
    expires_at: s.expires_at ?? 0,
    user: {
      id: s.user.id,
      email: s.user.email ?? '',
    },
  };
}

interface SupabaseSignInError {
  message?: string | undefined;
  code?: string | undefined;
  status?: number | undefined;
}

function mapSupabaseError(err: SupabaseSignInError): string {
  const code = err.code ?? '';
  const message = err.message ?? '';
  if (code === 'invalid_credentials' || message.includes('Invalid login credentials')) {
    return 'Invalid email or password';
  }
  if (code === 'email_not_confirmed' || message.includes('Email not confirmed')) {
    return 'Please confirm your email before signing in';
  }
  return 'Authentication failed, try again in a moment';
}

const initialData: AuthStateData = {
  session: null,
  profile: null,
  status: 'unauthenticated',
  error: null,
  authed: false,
  initialized: false,
};

export const useAuthStore = create<AuthState>()((set, get) => {
  // Wraps any partial state update so `authed` stays a mirror of `status`.
  // Also flips `initialized` true the moment we reach a settled state
  // (authenticated / unauthenticated) — i.e. the first real session check has
  // resolved. Once true it stays true.
  const apply = (patch: Partial<AuthStateData>): void => {
    const nextStatus = patch.status ?? get().status;
    const settled = nextStatus === 'authenticated' || nextStatus === 'unauthenticated';
    set({
      ...patch,
      authed: nextStatus === 'authenticated',
      initialized: get().initialized || settled,
    });
  };

  return {
    ...initialData,

    async signIn(email, password) {
      // Mock-mode: bypass supabase entirely, drop the user straight into the
      // app with a mock session + profile.
      if (!isV2ApiEnabled()) {
        apply({
          session: MOCK_SESSION,
          profile: MOCK_PROFILE,
          status: 'authenticated',
          error: null,
        });
        return;
      }

      apply({ status: 'authenticating', error: null });

      let supabase: ReturnType<typeof getSupabaseClient>;
      try {
        supabase = getSupabaseClient();
      } catch (err) {
        // Missing env vars — surface a usable error rather than crashing.
        apply({
          status: 'unauthenticated',
          error: (err as Error).message,
        });
        return;
      }

      const { data, error } = await supabase.auth.signInWithPassword({ email, password });

      if (error) {
        apply({ status: 'unauthenticated', error: mapSupabaseError(error) });
        return;
      }
      if (!data.session) {
        apply({ status: 'unauthenticated', error: 'Sign-in returned no session' });
        return;
      }

      apply({
        session: mapSupabaseSession(data.session),
        status: 'authenticated',
        error: null,
      });
      // Block until profile lands so the UI can branch on `organization_id`.
      await get().fetchProfile();
    },

    async signOut() {
      if (isV2ApiEnabled()) {
        const supabase = (() => {
          try {
            return getSupabaseClient();
          } catch {
            return null;
          }
        })();
        if (supabase) {
          try {
            await supabase.auth.signOut();
          } catch {
            // Best-effort; supabase-js may have already cleared local state.
          }
        }
      }
      apply({ session: null, profile: null, status: 'unauthenticated', error: null });
      // Wipe both the legacy key and let supabase-js own its own teardown.
      clearLegacyStorage();
      // Drop all cached query data so the next user on this device can't see it.
      clearAsyncCache();
    },

    async loadFromStorage() {
      // Mock mode: jump straight to authenticated, skip storage entirely.
      if (!isV2ApiEnabled()) {
        apply({
          session: MOCK_SESSION,
          profile: MOCK_PROFILE,
          status: 'authenticated',
          error: null,
        });
        return;
      }

      // One-time migration: scrub the old fetch-era persisted blob if it's
      // still hanging around in someone's browser.
      clearLegacyStorage();

      let supabase: ReturnType<typeof getSupabaseClient>;
      try {
        supabase = getSupabaseClient();
      } catch {
        // Env not configured — treat as unauthenticated, login page will show.
        apply({ status: 'unauthenticated' });
        return;
      }

      const { data } = await supabase.auth.getSession();
      if (data.session) {
        apply({
          session: mapSupabaseSession(data.session),
          status: 'authenticated',
          error: null,
        });
        // Re-fetch profile so cold-loaded sessions don't serve stale org /
        // staff data. Fire-and-forget on purpose.
        void get().fetchProfile();
      } else {
        apply({ status: 'unauthenticated' });
      }
    },

    bindAuthListener() {
      if (!isV2ApiEnabled()) {
        // Mock mode: no listener needed.
        return () => undefined;
      }
      let supabase: ReturnType<typeof getSupabaseClient>;
      try {
        supabase = getSupabaseClient();
      } catch {
        return () => undefined;
      }

      const {
        data: { subscription },
      } = supabase.auth.onAuthStateChange((event, session) => {
        if (event === 'SIGNED_OUT' || !session) {
          apply({
            session: null,
            profile: null,
            status: 'unauthenticated',
            error: null,
          });
          // Also clear cached query data on listener-driven sign-out (token
          // expiry / revocation / sign-out from another tab), not just the
          // explicit signOut() action — closes the cross-tab stale-paint vector.
          clearAsyncCache();
          return;
        }
        if (event === 'TOKEN_REFRESHED' || event === 'SIGNED_IN' || event === 'USER_UPDATED') {
          apply({
            session: mapSupabaseSession(session),
            status: 'authenticated',
            error: null,
          });
          void get().fetchProfile();
        }
      });

      return () => subscription.unsubscribe();
    },

    async fetchProfile() {
      if (!isV2ApiEnabled()) {
        apply({ profile: MOCK_PROFILE });
        return;
      }
      const session = get().session;
      if (!session) return;

      try {
        const body = await v2Client.get<{
          id?: unknown;
          email?: unknown;
          organization_id?: unknown;
          is_staff?: unknown;
          name?: unknown;
          has_pending_invite?: unknown;
        }>('/api/v2/auth/me');
        if (!body || typeof body !== 'object') return;
        const profile: AuthProfile = {
          id: typeof body.id === 'string' ? body.id : session.user.id,
          email: typeof body.email === 'string' ? body.email : session.user.email,
          organization_id: typeof body.organization_id === 'string' ? body.organization_id : null,
          is_staff: typeof body.is_staff === 'boolean' ? body.is_staff : false,
          name: typeof body.name === 'string' ? body.name : null,
          has_pending_invite:
            typeof body.has_pending_invite === 'boolean' ? body.has_pending_invite : false,
        };
        apply({ profile });

        if (profile.has_pending_invite) {
          try {
            await teamSvc.acceptInvite();
            apply({ profile: { ...profile, has_pending_invite: false } });
            emit('team:updated');
          } catch {
            // Non-fatal — user is authenticated, invite cleanup will retry on next login.
          }
        }
      } catch (err) {
        // v2Client maps HTTP errors to ServiceError with a `code` field.
        const code = (err as { code?: string }).code;
        if (code === 'forbidden') {
          // 401/403: in the 401 path the v2-client already attempted the
          // refresh via the unauthorized handler; if it bubbled to here the
          // session is unrecoverable. In the pure 403 case (valid session,
          // no org), keep the session but surface a placeholder profile.
          // We disambiguate via httpStatus when available.
          const httpStatus = (err as { httpStatus?: number }).httpStatus;
          if (httpStatus === 403) {
            apply({
              profile: {
                id: session.user.id,
                email: session.user.email,
                ...PLACEHOLDER_PROFILE_NO_ORG,
              },
            });
            return;
          }
          // 401 after refresh failed: sign out so the UI redirects to /login.
          await get().signOut();
          return;
        }
        // Network / 5xx / parsing — leave session intact, profile unchanged.
      }
    },
  };
});
