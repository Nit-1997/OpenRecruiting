import { describe, expect, it } from 'bun:test';
import {
  formatScheduledDate,
  formatScheduledDateTime,
  formatScheduledTime,
} from './format-scheduled';

describe('formatScheduledDate', () => {
  it('renders in the saved scheduling_timezone, not browser tz', () => {
    // 3pm ET stored as UTC. Viewer in LA would see 12pm without the saved tz.
    const iso = '2026-05-21T19:00:00+00:00';
    expect(formatScheduledDate(iso, 'America/New_York')).toBe('May 21');
  });

  it('falls back to browser tz when scheduling_timezone is null', () => {
    expect(formatScheduledDate('2026-05-21T19:00:00+00:00', null)).toMatch(
      /^[A-Z][a-z]{2} \d{1,2}$/,
    );
  });

  it('returns empty string for null input', () => {
    expect(formatScheduledDate(null, 'America/New_York')).toBe('');
  });

  it('returns empty string for invalid date input', () => {
    expect(formatScheduledDate('not-a-date', 'America/New_York')).toBe('');
  });
});

describe('formatScheduledTime', () => {
  it('renders 3pm ET as 3:00 PM with EDT offset', () => {
    const iso = '2026-05-21T19:00:00+00:00';
    const result = formatScheduledTime(iso, 'America/New_York');
    expect(result).toContain('3:00 PM');
    expect(result).toMatch(/GMT-?\d+|EDT|EST/);
  });

  it('renders 3pm IST with +5:30 offset', () => {
    const iso = '2026-05-21T09:30:00+00:00'; // 3pm IST
    const result = formatScheduledTime(iso, 'Asia/Kolkata');
    expect(result).toContain('3:00 PM');
  });
});

describe('formatScheduledDateTime', () => {
  it('combines date + time with offset suffix in the saved zone', () => {
    const iso = '2026-05-21T19:00:00+00:00';
    const result = formatScheduledDateTime(iso, 'America/New_York');
    // Format: "Thu, May 21 at 3:00 PM GMT-4" (offset string varies)
    expect(result).toContain('May 21');
    expect(result).toContain('3:00 PM');
  });

  it('returns empty string for null input', () => {
    expect(formatScheduledDateTime(null, 'America/New_York')).toBe('');
  });
});
