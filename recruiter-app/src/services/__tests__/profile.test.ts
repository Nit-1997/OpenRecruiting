import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { clearDb } from '../mock-db';
import * as profile from '../profile';
import { seedDb } from '../seed';

beforeEach(() => {
  clearDb();
  if (typeof window !== 'undefined') window.__LATENCY_MS = 0;
  seedDb();
});
afterEach(() => clearDb());

describe('profile service', () => {
  test('updateTimezone validates IANA format', async () => {
    await expect(profile.updateTimezone('NotATZ')).rejects.toThrow(/timezone/);
  });

  test('updateName recomputes initials', async () => {
    const p = await profile.updateName('Ada Lovelace');
    expect(p.avatar_initials).toBe('AL');
  });

  test('notification prefs roundtrip', async () => {
    await profile.updateNotificationPrefs({ email_weekly_digest: false });
    const prefs = await profile.getNotificationPrefs();
    expect(prefs.email_weekly_digest).toBe(false);
  });
});
