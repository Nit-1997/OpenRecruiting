// IMPORTANT: env must be set BEFORE the store module is imported. Several
// modules in the import chain (v2-client.ts) capture eager constants at
// module-load time, so URL/key need to be in process.env when the module
// graph first resolves. NEXT_PUBLIC_V2_API is read dynamically per call by
// `isV2ApiEnabled()`, so we set it per-test in beforeEach below — that
// avoids the cross-file race with bun's concurrent test runner.
process.env.NEXT_PUBLIC_API_URL = 'http://test.invalid';
process.env.NEXT_PUBLIC_SUPABASE_URL = 'http://supabase.test.invalid';
process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'anon-test-key';

import { afterAll, afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';

beforeEach(() => {
  // Override test-setup.ts's `false` default — this file exercises the
  // v2-API auth path and needs `true` for every test it runs.
  process.env.NEXT_PUBLIC_V2_API = 'true';
});
import { ServiceError } from '@/services/service-error';

// --- Mock the supabase singleton ---------------------------------------------
//
// We stub the module that the store imports rather than fish supabase-js's
// internals out by hand. Each test installs the responses it cares about by
// reassigning the mockable handles below.

const mockSignInWithPassword = mock(
  async (_args: {
    email: string;
    password: string;
  }): Promise<{
    data: { session: unknown | null };
    error: { message: string; code?: string } | null;
  }> => ({ data: { session: null }, error: { message: 'unset' } }),
);
const mockSignOut = mock(async (): Promise<{ error: unknown }> => ({ error: null }));
const mockGetSession = mock(
  async (): Promise<{ data: { session: unknown | null } }> => ({
    data: { session: null },
  }),
);
const mockRefreshSession = mock(
  async (): Promise<{
    data: { session: unknown | null };
    error: { message: string; code?: string } | null;
  }> => ({ data: { session: null }, error: null }),
);
const mockOnAuthStateChange = mock(
  (
    _cb: (event: string, session: unknown | null) => void,
  ): { data: { subscription: { unsubscribe: () => void } } } => ({
    data: { subscription: { unsubscribe: () => undefined } },
  }),
);

function makeFakeSupabase() {
  return {
    auth: {
      signInWithPassword: mockSignInWithPassword,
      signOut: mockSignOut,
      getSession: mockGetSession,
      refreshSession: mockRefreshSession,
      onAuthStateChange: mockOnAuthStateChange,
    },
  };
}

mock.module('@/lib/supabase', () => ({
  getSupabaseClient: () => makeFakeSupabase(),
  getSupabaseClientOrNull: () => makeFakeSupabase(),
}));

// --- Mock v2Client so fetchProfile doesn't hit the real network --------------

let nextMeResponse: unknown = null;
let nextMeError: unknown = null;
let meCallCount = 0;

mock.module('@/lib/v2-client', () => ({
  v2Client: {
    get: (path: string) => {
      if (path === '/api/v2/auth/me') {
        meCallCount += 1;
        if (nextMeError) return Promise.reject(nextMeError);
        return Promise.resolve(nextMeResponse);
      }
      return Promise.resolve(null);
    },
    post: () => Promise.resolve(null),
    put: () => Promise.resolve(null),
    delete: () => Promise.resolve(null),
  },
  setV2TokenGetter: () => undefined,
  setV2UnauthorizedHandler: () => undefined,
}));

// Import AFTER the mocks register so the store binds to the stubs.
const { useAuthStore } = await import('../auth-store');

const SUPABASE_SESSION = {
  access_token: 'access-1',
  refresh_token: 'refresh-1',
  expires_at: Math.floor(Date.now() / 1000) + 60 * 60, // 1h ahead
  token_type: 'bearer',
  user: { id: 'user-1', email: 'jane@example.com' },
};

const FAKE_PROFILE = {
  id: 'user-1',
  email: 'jane@example.com',
  organization_id: 'org-1',
  is_staff: false,
  name: 'Jane Recruiter',
};

function resetStore(): void {
  useAuthStore.setState({
    session: null,
    profile: null,
    status: 'unauthenticated',
    error: null,
    authed: false,
    // `initialized` MUST be reset too. It is a sticky one-way latch (false →
    // true on the first settled session check, never back). The prior helper
    // omitted it, so once any test settled the store it stayed `true` for every
    // subsequent test — silently defeating the false-before-first-check
    // invariant below. Reset it here so each test starts from a true cold boot.
    initialized: false,
  });
  if (typeof localStorage !== 'undefined') localStorage.clear();
}

function resetMocks(): void {
  mockSignInWithPassword.mockReset();
  mockSignOut.mockReset();
  mockGetSession.mockReset();
  mockRefreshSession.mockReset();
  mockOnAuthStateChange.mockReset();
  // Sensible defaults so unused mocks don't crash a test that doesn't pin them.
  mockSignOut.mockImplementation(async () => ({ error: null }));
  mockOnAuthStateChange.mockImplementation(() => ({
    data: { subscription: { unsubscribe: () => undefined } },
  }));
  nextMeResponse = null;
  nextMeError = null;
  meCallCount = 0;
}

beforeEach(() => {
  resetStore();
  resetMocks();
});

afterEach(() => {
  // bun's `mock.restore()` resets timers/spies but doesn't touch mock.module
  // registrations, which is what we want here.
});

afterAll(() => {
  delete process.env.NEXT_PUBLIC_V2_API;
  delete process.env.NEXT_PUBLIC_API_URL;
  delete process.env.NEXT_PUBLIC_SUPABASE_URL;
  delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
});

describe('auth-store - signIn', () => {
  test('success: stores session, fetches profile, authed=true', async () => {
    mockSignInWithPassword.mockImplementation(async () => ({
      data: { session: SUPABASE_SESSION },
      error: null,
    }));
    nextMeResponse = FAKE_PROFILE;

    await useAuthStore.getState().signIn('jane@example.com', 'hunter2');

    const s = useAuthStore.getState();
    expect(s.status).toBe('authenticated');
    expect(s.authed).toBe(true);
    expect(s.session?.access_token).toBe('access-1');
    expect(s.profile?.organization_id).toBe('org-1');
    expect(s.error).toBeNull();
    expect(meCallCount).toBe(1);
  });

  test('invalid_credentials: surfaces user-friendly error, stays unauthenticated', async () => {
    mockSignInWithPassword.mockImplementation(async () => ({
      data: { session: null },
      error: { message: 'Invalid login credentials', code: 'invalid_credentials' },
    }));

    await useAuthStore.getState().signIn('jane@example.com', 'wrong');

    const s = useAuthStore.getState();
    expect(s.status).toBe('unauthenticated');
    expect(s.authed).toBe(false);
    expect(s.session).toBeNull();
    expect(s.error).toBe('Invalid email or password');
  });

  test('email_not_confirmed: surfaces confirmation-prompt error', async () => {
    mockSignInWithPassword.mockImplementation(async () => ({
      data: { session: null },
      error: { message: 'Email not confirmed', code: 'email_not_confirmed' },
    }));

    await useAuthStore.getState().signIn('jane@example.com', 'hunter2');

    expect(useAuthStore.getState().error).toBe('Please confirm your email before signing in');
    expect(useAuthStore.getState().status).toBe('unauthenticated');
  });

  test('generic supabase error: falls back to generic copy', async () => {
    mockSignInWithPassword.mockImplementation(async () => ({
      data: { session: null },
      error: { message: 'Some 500 thing', code: 'unexpected' },
    }));

    await useAuthStore.getState().signIn('jane@example.com', 'hunter2');

    expect(useAuthStore.getState().error).toBe('Authentication failed, try again in a moment');
  });

  test('no error but no session either: explicit error message', async () => {
    mockSignInWithPassword.mockImplementation(async () => ({
      data: { session: null },
      error: null,
    }));

    await useAuthStore.getState().signIn('jane@example.com', 'hunter2');

    expect(useAuthStore.getState().status).toBe('unauthenticated');
    expect(useAuthStore.getState().error).toBe('Sign-in returned no session');
  });
});

describe('auth-store - signOut', () => {
  test('clears state and calls supabase.auth.signOut', async () => {
    useAuthStore.setState({
      session: {
        access_token: SUPABASE_SESSION.access_token,
        refresh_token: SUPABASE_SESSION.refresh_token,
        expires_at: SUPABASE_SESSION.expires_at,
        user: { id: SUPABASE_SESSION.user.id, email: SUPABASE_SESSION.user.email },
      },
      profile: FAKE_PROFILE,
      status: 'authenticated',
      authed: true,
    });

    await useAuthStore.getState().signOut();

    expect(useAuthStore.getState().session).toBeNull();
    expect(useAuthStore.getState().profile).toBeNull();
    expect(useAuthStore.getState().status).toBe('unauthenticated');
    expect(useAuthStore.getState().authed).toBe(false);
    expect(mockSignOut).toHaveBeenCalledTimes(1);
  });

  test('supabase signOut failure does not propagate', async () => {
    useAuthStore.setState({
      session: {
        access_token: SUPABASE_SESSION.access_token,
        refresh_token: SUPABASE_SESSION.refresh_token,
        expires_at: SUPABASE_SESSION.expires_at,
        user: { id: SUPABASE_SESSION.user.id, email: SUPABASE_SESSION.user.email },
      },
      status: 'authenticated',
      authed: true,
    });
    mockSignOut.mockImplementation(async () => {
      throw new Error('network gone');
    });

    await useAuthStore.getState().signOut();
    expect(useAuthStore.getState().session).toBeNull();
    expect(useAuthStore.getState().status).toBe('unauthenticated');
  });

  test('removes legacy openrecruiting.auth.v2 storage entry', async () => {
    localStorage.setItem('openrecruiting.auth.v2', JSON.stringify({ state: { session: {} } }));
    await useAuthStore.getState().signOut();
    expect(localStorage.getItem('openrecruiting.auth.v2')).toBeNull();
  });
});

describe('auth-store - loadFromStorage', () => {
  test('active supabase session: hydrates store, triggers profile fetch', async () => {
    mockGetSession.mockImplementation(async () => ({
      data: { session: SUPABASE_SESSION },
    }));
    nextMeResponse = FAKE_PROFILE;

    await useAuthStore.getState().loadFromStorage();

    expect(useAuthStore.getState().session?.access_token).toBe('access-1');
    expect(useAuthStore.getState().status).toBe('authenticated');
    expect(useAuthStore.getState().authed).toBe(true);

    // fetchProfile is fired-and-forgotten; let microtasks drain.
    await new Promise((r) => setTimeout(r, 0));
    expect(meCallCount).toBe(1);
  });

  test('no session: stays unauthenticated', async () => {
    mockGetSession.mockImplementation(async () => ({ data: { session: null } }));

    await useAuthStore.getState().loadFromStorage();
    expect(useAuthStore.getState().status).toBe('unauthenticated');
    expect(useAuthStore.getState().session).toBeNull();
  });

  test('always scrubs the legacy openrecruiting.auth.v2 key', async () => {
    localStorage.setItem('openrecruiting.auth.v2', 'something stale');
    mockGetSession.mockImplementation(async () => ({ data: { session: null } }));

    await useAuthStore.getState().loadFromStorage();
    expect(localStorage.getItem('openrecruiting.auth.v2')).toBeNull();
  });
});

describe('auth-store - fetchProfile', () => {
  test('200: populates profile from /api/v2/auth/me', async () => {
    useAuthStore.setState({
      session: {
        access_token: 'a',
        refresh_token: 'r',
        expires_at: SUPABASE_SESSION.expires_at,
        user: { id: 'user-1', email: 'jane@example.com' },
      },
      status: 'authenticated',
      authed: true,
    });
    nextMeResponse = FAKE_PROFILE;

    await useAuthStore.getState().fetchProfile();
    expect(useAuthStore.getState().profile?.organization_id).toBe('org-1');
  });

  test('403 (no org): keeps session, surfaces placeholder profile', async () => {
    useAuthStore.setState({
      session: {
        access_token: 'a',
        refresh_token: 'r',
        expires_at: SUPABASE_SESSION.expires_at,
        user: { id: 'user-1', email: 'jane@example.com' },
      },
      status: 'authenticated',
      authed: true,
    });
    nextMeError = new ServiceError('forbidden', 'no org', { httpStatus: 403 });

    await useAuthStore.getState().fetchProfile();

    const s = useAuthStore.getState();
    expect(s.session).not.toBeNull();
    expect(s.profile?.organization_id).toBeNull();
    expect(s.profile?.email).toBe('jane@example.com');
  });

  test('401 reaching the store (v2-client retry already failed): signs out', async () => {
    useAuthStore.setState({
      session: {
        access_token: 'a',
        refresh_token: 'r',
        expires_at: SUPABASE_SESSION.expires_at,
        user: { id: 'user-1', email: 'jane@example.com' },
      },
      status: 'authenticated',
      authed: true,
    });
    nextMeError = new ServiceError('forbidden', 'expired', { httpStatus: 401 });

    await useAuthStore.getState().fetchProfile();
    expect(useAuthStore.getState().session).toBeNull();
    expect(useAuthStore.getState().status).toBe('unauthenticated');
  });

  test('network error: session intact, profile unchanged', async () => {
    useAuthStore.setState({
      session: {
        access_token: 'a',
        refresh_token: 'r',
        expires_at: SUPABASE_SESSION.expires_at,
        user: { id: 'user-1', email: 'jane@example.com' },
      },
      profile: FAKE_PROFILE,
      status: 'authenticated',
      authed: true,
    });
    nextMeError = new ServiceError('network', 'down');

    await useAuthStore.getState().fetchProfile();
    expect(useAuthStore.getState().session).not.toBeNull();
    expect(useAuthStore.getState().profile?.id).toBe('user-1');
  });
});

describe('auth-store - bindAuthListener', () => {
  test('SIGNED_OUT event clears the store', () => {
    useAuthStore.setState({
      session: {
        access_token: 'a',
        refresh_token: 'r',
        expires_at: SUPABASE_SESSION.expires_at,
        user: { id: 'user-1', email: 'jane@example.com' },
      },
      status: 'authenticated',
      authed: true,
    });
    type Cb = (event: string, session: unknown | null) => void;
    const holder: { cb: Cb | null } = { cb: null };
    mockOnAuthStateChange.mockImplementation((cb) => {
      holder.cb = cb;
      return { data: { subscription: { unsubscribe: () => undefined } } };
    });

    useAuthStore.getState().bindAuthListener();
    expect(holder.cb).not.toBeNull();
    holder.cb?.('SIGNED_OUT', null);

    expect(useAuthStore.getState().status).toBe('unauthenticated');
    expect(useAuthStore.getState().session).toBeNull();
  });

  test('TOKEN_REFRESHED event updates the session in place', () => {
    type Cb = (event: string, session: unknown | null) => void;
    const holder: { cb: Cb | null } = { cb: null };
    mockOnAuthStateChange.mockImplementation((cb) => {
      holder.cb = cb;
      return { data: { subscription: { unsubscribe: () => undefined } } };
    });

    useAuthStore.getState().bindAuthListener();
    holder.cb?.('TOKEN_REFRESHED', {
      ...SUPABASE_SESSION,
      access_token: 'access-refreshed',
    });

    expect(useAuthStore.getState().status).toBe('authenticated');
    expect(useAuthStore.getState().session?.access_token).toBe('access-refreshed');
  });

  test('returns an unsubscribe that calls subscription.unsubscribe', () => {
    let unsubCalls = 0;
    mockOnAuthStateChange.mockImplementation(() => ({
      data: {
        subscription: {
          unsubscribe: () => {
            unsubCalls += 1;
          },
        },
      },
    }));

    const unsub = useAuthStore.getState().bindAuthListener();
    unsub();
    expect(unsubCalls).toBe(1);
  });
});

describe('auth-store - mock mode', () => {
  test('signIn in mock mode bypasses supabase entirely', async () => {
    const prev = process.env.NEXT_PUBLIC_V2_API;
    process.env.NEXT_PUBLIC_V2_API = 'false';
    try {
      await useAuthStore.getState().signIn('whoever@example.com', 'anything');
      const s = useAuthStore.getState();
      expect(s.status).toBe('authenticated');
      expect(s.authed).toBe(true);
      expect(s.profile?.email).toBe('demo@example.com');
      expect(mockSignInWithPassword).not.toHaveBeenCalled();
    } finally {
      process.env.NEXT_PUBLIC_V2_API = prev;
    }
  });

  test('loadFromStorage in mock mode auto-authenticates', async () => {
    const prev = process.env.NEXT_PUBLIC_V2_API;
    process.env.NEXT_PUBLIC_V2_API = 'false';
    try {
      await useAuthStore.getState().loadFromStorage();
      expect(useAuthStore.getState().status).toBe('authenticated');
      expect(useAuthStore.getState().profile?.email).toBe('demo@example.com');
      expect(mockGetSession).not.toHaveBeenCalled();
    } finally {
      process.env.NEXT_PUBLIC_V2_API = prev;
    }
  });
});

// FE-T1: the `initialized` flag is the documented anti-redirect-loop invariant
// (see auth-store.ts:42-45). Auth gates MUST wait for it before redirecting, or
// they act on the initial `unauthenticated` placeholder and bounce an authed
// user to the login app mid-hydration — an infinite cross-subdomain redirect
// loop with landing. These tests pin the contract: false until the FIRST
// settled session check resolves, then sticky-true (one-way latch).
describe('auth-store - initialized invariant', () => {
  test('false at cold boot (before any session check resolves)', () => {
    // resetStore() runs in beforeEach and now resets `initialized` to false.
    expect(useAuthStore.getState().initialized).toBe(false);
  });

  test('loadFromStorage with no session flips initialized true (settled = unauthenticated)', async () => {
    expect(useAuthStore.getState().initialized).toBe(false);
    mockGetSession.mockImplementation(async () => ({ data: { session: null } }));

    await useAuthStore.getState().loadFromStorage();

    expect(useAuthStore.getState().status).toBe('unauthenticated');
    expect(useAuthStore.getState().initialized).toBe(true);
  });

  test('loadFromStorage with an active session flips initialized true (settled = authenticated)', async () => {
    expect(useAuthStore.getState().initialized).toBe(false);
    mockGetSession.mockImplementation(async () => ({ data: { session: SUPABASE_SESSION } }));
    nextMeResponse = FAKE_PROFILE;

    await useAuthStore.getState().loadFromStorage();

    expect(useAuthStore.getState().status).toBe('authenticated');
    expect(useAuthStore.getState().initialized).toBe(true);
  });

  test('the transient authenticating state does NOT flip initialized (only settled states do)', async () => {
    expect(useAuthStore.getState().initialized).toBe(false);
    // signIn sets status='authenticating' first; that is NOT a settled state, so
    // initialized must stay false until the call resolves to a settled status.
    // Hold the resolver on an object (TS can't narrow a bare `let` assigned
    // only inside the executor — same pattern bindAuthListener tests use).
    const gate: { resolve: () => void } = { resolve: () => undefined };
    mockSignInWithPassword.mockImplementation(
      () =>
        new Promise((resolve) => {
          gate.resolve = () => resolve({ data: { session: null }, error: null });
        }),
    );

    const inFlight = useAuthStore.getState().signIn('jane@example.com', 'hunter2');
    // While authenticating, the gate must not have been told auth is initialized.
    expect(useAuthStore.getState().status).toBe('authenticating');
    expect(useAuthStore.getState().initialized).toBe(false);

    gate.resolve();
    await inFlight;
    // Now settled (unauthenticated) → initialized latches true.
    expect(useAuthStore.getState().status).toBe('unauthenticated');
    expect(useAuthStore.getState().initialized).toBe(true);
  });

  test('initialized is a one-way latch: stays true across a later transition', async () => {
    // First settle the store.
    mockGetSession.mockImplementation(async () => ({ data: { session: null } }));
    await useAuthStore.getState().loadFromStorage();
    expect(useAuthStore.getState().initialized).toBe(true);

    // A subsequent sign-in attempt that goes back through 'authenticating' must
    // not un-set initialized — gates that already let the user through stay open.
    mockSignInWithPassword.mockImplementation(async () => ({
      data: { session: SUPABASE_SESSION },
      error: null,
    }));
    nextMeResponse = FAKE_PROFILE;
    await useAuthStore.getState().signIn('jane@example.com', 'hunter2');

    expect(useAuthStore.getState().initialized).toBe(true);
  });

  test('resetStore() helper resets initialized back to false (guards the test invariant itself)', () => {
    useAuthStore.setState({ initialized: true });
    expect(useAuthStore.getState().initialized).toBe(true);
    resetStore();
    expect(useAuthStore.getState().initialized).toBe(false);
  });
});
