import type { NotificationPreferences, Profile } from '@/domain';
import { isV2ApiEnabled } from '@/lib/env';
import { v2Client } from '@/lib/v2-client';
import { emit } from './events';
import { simulate } from './latency';
import { getDb, persist } from './mock-db';
import { notImplementedInV2, ServiceError } from './service-error';

// Shape of GET /api/v2/auth/me (MeResponse). The backend does not store the
// display-only profile fields below, so they are derived client-side.
interface ApiMe {
  id: string;
  email: string;
  name: string | null;
  organization_id: string | null;
  is_staff: boolean;
  has_pending_invite: boolean;
}

function deriveInitials(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  const first = parts[0]?.[0] ?? '';
  const second = parts[1]?.[0] ?? '';
  return (first + second || name.slice(0, 2)).toUpperCase();
}

function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

function toProfile(me: ApiMe): Profile {
  const name = me.name?.trim() || me.email.split('@')[0] || me.email;
  return {
    id: me.id,
    user_id: me.id,
    name,
    email: me.email,
    avatar_initials: deriveInitials(name),
    avatar_color: '#EEE8DD',
    timezone: browserTimezone(),
    onboarding_completed: true,
  };
}

export async function get(): Promise<Profile> {
  if (isV2ApiEnabled()) {
    return toProfile(await v2Client.get<ApiMe>('/api/v2/auth/me'));
  }
  await simulate();
  return structuredClone(getDb().profile);
}

export async function updateTimezone(tz: string): Promise<Profile> {
  if (isV2ApiEnabled()) throw notImplementedInV2('profile.updateTimezone');
  await simulate();
  if (!tz.includes('/')) {
    throw new ServiceError('validation', 'Invalid IANA timezone', { field: 'timezone' });
  }
  const db = getDb();
  db.profile.timezone = tz;
  persist();
  emit('profile:updated');
  return structuredClone(db.profile);
}

export async function updateName(name: string): Promise<Profile> {
  if (isV2ApiEnabled()) throw notImplementedInV2('profile.updateName');
  await simulate();
  if (!name.trim()) throw new ServiceError('validation', 'Name is required', { field: 'name' });
  const db = getDb();
  db.profile.name = name.trim();
  db.profile.avatar_initials = name
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('');
  persist();
  emit('profile:updated');
  return structuredClone(db.profile);
}

export async function getNotificationPrefs(): Promise<NotificationPreferences> {
  if (isV2ApiEnabled()) throw notImplementedInV2('profile.getNotificationPrefs');
  await simulate();
  return structuredClone(getDb().notification_prefs);
}

export async function updateNotificationPrefs(
  patch: Partial<Omit<NotificationPreferences, 'user_id'>>,
): Promise<NotificationPreferences> {
  if (isV2ApiEnabled()) throw notImplementedInV2('profile.updateNotificationPrefs');
  await simulate();
  const db = getDb();
  db.notification_prefs = { ...db.notification_prefs, ...patch };
  persist();
  emit('notification_prefs:updated');
  return structuredClone(db.notification_prefs);
}
