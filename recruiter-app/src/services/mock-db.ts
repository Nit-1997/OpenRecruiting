import type {
  ActivityEvent,
  BillingOverview,
  Candidate,
  CandidateRound,
  FeedbackEntry,
  Integration,
  Invite,
  NotificationPreferences,
  Profile,
  Requisition,
  RoundRecording,
  TeamMember,
} from '@/domain';

export interface MockDb {
  requisitions: Requisition[];
  candidates: Candidate[];
  candidate_rounds: CandidateRound[];
  feedback_entries: FeedbackEntry[];
  recordings: RoundRecording[];
  team_members: TeamMember[];
  invites: Invite[];
  billing: BillingOverview;
  integrations: Integration[];
  profile: Profile;
  notification_prefs: NotificationPreferences;
  activity: ActivityEvent[];
  _meta: { seeded_at: string; version: number };
}

// Bump this suffix whenever the seed shape or authored fixtures change in a
// way that should flush any client-cached DB. The app reads `openrecruiting:mock-db:*`
// keys lazily in `getDb()`; bumping the suffix naturally invalidates stale
// caches (new key is absent → fresh seed runs) without a manual clear.
const STORAGE_KEY_PREFIX = 'openrecruiting:mock-db:';
const STORAGE_KEY = `${STORAGE_KEY_PREFIX}v9`;
let _state: MockDb | null = null;

/**
 * Drop every old `openrecruiting:mock-db:*` storage key that isn't the active one.
 * Cumulative version bumps used to leave orphan blobs sitting in localStorage
 * — combined with the ~1MB seed and Safari's stricter per-origin quota, that
 * was enough to hit QuotaExceededError on first save of a fresh key. Cheap to
 * run on every read: filters string keys only, no JSON.parse on the values.
 */
function pruneOrphanStorageKeys(): void {
  if (typeof window === 'undefined') return;
  const ls = window.localStorage;
  // Snapshot the key list — removing during iteration shifts indices.
  const orphans: string[] = [];
  for (let i = 0; i < ls.length; i++) {
    const key = ls.key(i);
    if (key && key.startsWith(STORAGE_KEY_PREFIX) && key !== STORAGE_KEY) {
      orphans.push(key);
    }
  }
  orphans.forEach((k) => ls.removeItem(k));
}

interface SeedGlobal {
  __SEED?: () => MockDb;
}

function seedGlobal(): SeedGlobal {
  return globalThis as unknown as SeedGlobal;
}

export function getDb(): MockDb {
  if (_state) return _state;
  if (typeof window !== 'undefined') {
    // First read of the session — sweep orphan version blobs so they don't
    // pile up against the localStorage quota.
    pruneOrphanStorageKeys();
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) {
      try {
        _state = JSON.parse(raw) as MockDb;
        return _state;
      } catch {
        // corrupted — fall through to lazy seed
      }
    }
    const seedFn = seedGlobal().__SEED;
    if (seedFn) {
      _state = seedFn();
      persist();
      return _state;
    }
  }
  _state = emptyDb();
  persist();
  return _state;
}

export function resetDb(next: MockDb): void {
  _state = next;
  persist();
}

export function clearDb(): void {
  _state = null;
  if (typeof window !== 'undefined') window.localStorage.removeItem(STORAGE_KEY);
}

/**
 * Track whether we've already complained about quota exhaustion in this
 * session — once the orphan-prune + per-key purge both fail, the mock DB
 * runs in memory-only mode and there's no point spamming the console with
 * a warning on every subsequent mutation.
 */
let _quotaWarned = false;

export function persist(): void {
  if (typeof window === 'undefined' || !_state) return;
  const ls = window.localStorage;
  const payload = JSON.stringify(_state);
  try {
    ls.setItem(STORAGE_KEY, payload);
    return;
  } catch (err) {
    if (!isQuotaError(err)) throw err;
  }
  // Quota exceeded. First, drop orphan version blobs (cheap, common cause).
  pruneOrphanStorageKeys();
  try {
    ls.setItem(STORAGE_KEY, payload);
    return;
  } catch (err) {
    if (!isQuotaError(err)) throw err;
  }
  // Still no room. Drop our own current blob and retry — this trades
  // page-reload persistence for being able to save *something*; better
  // than crashing the UI on a non-essential write. If it still fails,
  // the mock DB simply runs in-memory for the rest of the session.
  try {
    ls.removeItem(STORAGE_KEY);
    ls.setItem(STORAGE_KEY, payload);
  } catch (err) {
    if (!isQuotaError(err)) throw err;
    if (!_quotaWarned) {
      _quotaWarned = true;
      console.warn(
        '[mock-db] localStorage quota exceeded; running in memory-only mode for this session.',
      );
    }
  }
}

function isQuotaError(err: unknown): boolean {
  if (!err || typeof err !== 'object') return false;
  const e = err as { name?: string; code?: number };
  // Standard name, Firefox legacy name, IE/old WebKit numeric code.
  return (
    e.name === 'QuotaExceededError' ||
    e.name === 'NS_ERROR_DOM_QUOTA_REACHED' ||
    e.code === 22 ||
    e.code === 1014
  );
}

function emptyDb(): MockDb {
  return {
    requisitions: [],
    candidates: [],
    candidate_rounds: [],
    feedback_entries: [],
    recordings: [],
    team_members: [],
    invites: [],
    billing: {
      intake_total: 5,
      intake_used: 0,
      intake_topup: 0,
      interview_total: 25,
      interview_used: 0,
      interview_topup: 0,
    },
    integrations: [],
    profile: {
      id: 'prof_1',
      user_id: 'user_1',
      name: 'Nitin',
      email: 'founder@example.com',
      avatar_initials: 'N',
      avatar_color: '#EEE8DD',
      timezone: 'America/Los_Angeles',
      onboarding_completed: true,
    },
    notification_prefs: {
      user_id: 'user_1',
      email_feedback_requests: true,
      email_interview_reminders: true,
      email_weekly_digest: false,
    },
    activity: [],
    _meta: { seeded_at: new Date(0).toISOString(), version: 1 },
  };
}

export function generateId(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36).slice(-4)}`;
}

export function nowIso(): string {
  return new Date().toISOString();
}
