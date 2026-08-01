// Tests for getDefaultSchedule — the pure helper that replaces the +3-day
// 5pm default (Bug #30). No React deps; runs in bun:test with happy-dom.

import { describe, expect, it, mock } from 'bun:test';
import { formatInTimeZone, fromZonedTime } from 'date-fns-tz';

// IMPORTANT: bun's `mock.module` is process-wide and leaks across test
// files. Replacing the full `@/services` index with a narrow stub here
// previously broke every later test that imported `candidates.create`,
// `requisitions.list`, etc. — same lesson as role-detail-page.test.tsx.
//
// `getDefaultSchedule` is a pure helper with no `@/services` dependency
// — these tests don't actually need any service surface. So we just
// don't mock it. If any future test in this file mounts the modal and
// triggers `interviews.schedule`, mock the SPECIFIC `@/services/interviews`
// submodule instead of the whole index.

mock.module('@/services/service-error', () => ({
  ServiceError: class ServiceError extends Error {
    constructor(
      public code: string,
      message: string,
      public meta?: unknown,
    ) {
      super(message);
    }
  },
}));

mock.module('./drawer', () => ({
  ModalShell: ({ children }: { children: React.ReactNode }) => children,
}));

import { getDefaultSchedule } from './schedule-modal';

describe('getDefaultSchedule', () => {
  it('defaults to the current wall-clock time in the chosen tz', () => {
    // 8:15 PM PT — picker should show that exact time, not snap to 8:30.
    // Snapping silently moves the time forward and confuses recruiters who
    // expect to see "now" and adjust from there (cofounder feedback).
    const fixedNow = new Date('2026-05-20T20:15:00-07:00');
    const result = getDefaultSchedule({ now: fixedNow, tz: 'America/Los_Angeles' });
    expect(result.date).toBe('2026-05-20');
    expect(result.time).toBe('20:15');
    expect(result.tz).toBe('America/Los_Angeles');
  });

  it('renders the same instant differently in different zones', () => {
    const instant = new Date('2026-05-20T20:15:00-07:00'); // 8:15pm PT
    const la = getDefaultSchedule({ now: instant, tz: 'America/Los_Angeles' });
    const ny = getDefaultSchedule({ now: instant, tz: 'America/New_York' });
    expect(la.time).toBe('20:15');
    expect(ny.time).toBe('23:15');
  });

  it('uses the browser TZ when none provided', () => {
    const result = getDefaultSchedule({ now: new Date('2026-05-20T12:00:00Z') });
    // Exact values depend on the env TZ, but the shape must be correct
    expect(result.tz).toBeTruthy();
    expect(result.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(result.time).toMatch(/^\d{2}:\d{2}$/);
  });
});

// These lock in the exact submit-payload shape that v1 production uses, so
// the recruiter's wall-clock time + IANA zone is preserved end-to-end. The
// schedule-modal submit handler runs this same `fromZonedTime` →
// `formatInTimeZone` pipeline before posting to the backend; a regression
// here (e.g. switching to naive `new Date(localStr)`, dropping the offset
// formatter, or accepting a non-IANA tz string) shows up as a wrong-time
// interview, which is the v1-vs-v2 divergence the cofounder flagged.
describe('schedule submit timezone pipeline', () => {
  function buildIsoForBackend(
    date: string,
    time: string,
    tz: string,
  ): { iso: string; utcMs: number } {
    const localStr = `${date}T${time}:00`;
    const utc = fromZonedTime(localStr, tz);
    return {
      iso: formatInTimeZone(utc, tz, "yyyy-MM-dd'T'HH:mm:ssxxx"),
      utcMs: utc.getTime(),
    };
  }

  it('LA wall-clock 3pm becomes -07:00 ISO (May DST)', () => {
    const r = buildIsoForBackend('2026-05-21', '15:00', 'America/Los_Angeles');
    expect(r.iso).toBe('2026-05-21T15:00:00-07:00');
    expect(r.utcMs).toBe(Date.UTC(2026, 4, 21, 22, 0, 0));
  });

  it('NY wall-clock 3pm becomes -04:00 ISO and a different UTC instant', () => {
    const r = buildIsoForBackend('2026-05-21', '15:00', 'America/New_York');
    expect(r.iso).toBe('2026-05-21T15:00:00-04:00');
    expect(r.utcMs).toBe(Date.UTC(2026, 4, 21, 19, 0, 0));
  });

  it('Kolkata wall-clock 3pm becomes +05:30 ISO (half-hour offset)', () => {
    const r = buildIsoForBackend('2026-05-21', '15:00', 'Asia/Kolkata');
    expect(r.iso).toBe('2026-05-21T15:00:00+05:30');
    expect(r.utcMs).toBe(Date.UTC(2026, 4, 21, 9, 30, 0));
  });

  it('Sydney wall-clock 9am in winter is +10:00 (no DST)', () => {
    const r = buildIsoForBackend('2026-06-15', '09:00', 'Australia/Sydney');
    expect(r.iso).toBe('2026-06-15T09:00:00+10:00');
    expect(r.utcMs).toBe(Date.UTC(2026, 5, 14, 23, 0, 0));
  });

  it('round-trips: rendering the backend ISO back in the saved zone returns the same wall clock', () => {
    // Backend stores TIMESTAMPTZ as UTC and returns +00:00. The drawer must
    // re-render it in the saved zone — otherwise a recruiter in LA viewing a
    // 3pm-ET interview sees 12pm, which looks like the time silently moved.
    const stored = '2026-05-21T19:00:00+00:00'; // 3pm ET in UTC
    const rendered = formatInTimeZone(new Date(stored), 'America/New_York', 'HH:mm');
    expect(rendered).toBe('15:00');
  });
});
