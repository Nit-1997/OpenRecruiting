// Component-level tests for the ScheduleModal — covers render paths,
// validation gating, and the submit pipeline end-to-end. Distinct from
// schedule-modal.test.tsx which unit-tests the pure `getDefaultSchedule`
// helper. Together these push the modal from ~6% line coverage toward
// ~70%+.

import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { cleanup, fireEvent, render } from '@testing-library/react';
import type { CandidateRound } from '@/domain';

// Capture interviews.schedule + reschedule via bun's `spyOn` rather than
// `mock.module`. `mock.module` is process-wide and irrestorable in bun —
// replacing the module silently broke every later test that imported
// schedule/cancel. `spyOn` patches the live module export and is restored
// in afterEach, so later test files see the real functions again.
const captured: { schedule: unknown[]; reschedule: unknown[] } = {
  schedule: [],
  reschedule: [],
};

import { spyOn } from 'bun:test';
import * as interviewsModule from '@/services/interviews';
import * as screeningModule from '@/services/screening';

let scheduleSpy: ReturnType<typeof spyOn> | null = null;
let rescheduleSpy: ReturnType<typeof spyOn> | null = null;
let inviteCrSpy: ReturnType<typeof spyOn> | null = null;

// We deliberately DO NOT `mock.module('./drawer', ...)` here. Replacing
// drawer.tsx with a narrow stub silently broke transcript-scrub and
// role-detail-page tests because the mock leaked to their imports
// (bun's mock.module is process-wide). The real ModalShell is light
// enough to use directly.

// Import AFTER mocks register so the modal binds to the stubs.
const { ScheduleModal } = await import('./schedule-modal');

function makeCandidateRound(overrides: Partial<CandidateRound> = {}): CandidateRound {
  return {
    id: 'cr-1',
    candidate_id: 'cand-1',
    round_id: 'round-1',
    status: 'pending',
    scheduled_at: null,
    scheduling_timezone: null,
    interviewer_email: null,
    interviewer_name: null,
    meeting_url: null,
    rating: null,
    summary: null,
    processing_status: 'none',
    feedback_questions: [],
    scorecard_status: 'pending',
    feedback_approved_at: null,
    feedback_approved_by_email: null,
    question_summaries: {},
    started_at: null,
    completed_at: null,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-01T00:00:00Z',
    ...overrides,
  } as CandidateRound;
}

beforeEach(() => {
  captured.schedule = [];
  captured.reschedule = [];
  scheduleSpy = spyOn(interviewsModule, 'schedule').mockImplementation(
    async (...args: unknown[]) => {
      captured.schedule.push(args);
      return undefined as never;
    },
  );
  rescheduleSpy = spyOn(interviewsModule, 'reschedule').mockImplementation(
    async (...args: unknown[]) => {
      captured.reschedule.push(args);
      return undefined as never;
    },
  );
});

afterEach(() => {
  cleanup();
  scheduleSpy?.mockRestore();
  rescheduleSpy?.mockRestore();
  inviteCrSpy?.mockRestore();
  inviteCrSpy = null;
});

describe('ScheduleModal — render paths', () => {
  test('shows "Schedule" CTA label for a pending round', () => {
    render(
      <ScheduleModal
        id="m"
        reqId="r"
        candidateId="c"
        roundId="round-1"
        existing={makeCandidateRound({ status: 'pending' })}
        onClose={() => {}}
      />,
    );
    const submit = document.getElementById('m-submit') as HTMLButtonElement;
    expect(submit.textContent?.trim()).toBe('Schedule');
  });

  test('shows "Reschedule" CTA label when round is already scheduled', () => {
    render(
      <ScheduleModal
        id="m"
        reqId="r"
        candidateId="c"
        roundId="round-1"
        existing={makeCandidateRound({
          status: 'scheduled',
          scheduled_at: '2026-06-01T19:00:00+00:00',
          scheduling_timezone: 'America/New_York',
          meeting_url: 'https://zoom.us/j/old',
          interviewer_email: 'old@example.com',
        })}
        onClose={() => {}}
      />,
    );
    const submit = document.getElementById('m-submit') as HTMLButtonElement;
    expect(submit.textContent?.trim()).toBe('Reschedule');
  });

  test('pre-fills date/time from existing scheduled_at in the saved tz', () => {
    render(
      <ScheduleModal
        id="m"
        reqId="r"
        candidateId="c"
        roundId="round-1"
        existing={makeCandidateRound({
          status: 'scheduled',
          // 3pm America/New_York on May 21 stored as UTC.
          scheduled_at: '2026-05-21T19:00:00+00:00',
          scheduling_timezone: 'America/New_York',
        })}
        onClose={() => {}}
      />,
    );
    const date = document.getElementById('m-date') as HTMLInputElement;
    const time = document.getElementById('m-time') as HTMLInputElement;
    expect(date.value).toBe('2026-05-21');
    expect(time.value).toBe('15:00');
  });

  test('pre-fills meeting_url, interviewer_email and name from existing values', () => {
    render(
      <ScheduleModal
        id="m"
        reqId="r"
        candidateId="c"
        roundId="round-1"
        existing={makeCandidateRound({
          status: 'scheduled',
          scheduled_at: '2026-06-01T19:00:00+00:00',
          scheduling_timezone: 'America/New_York',
          meeting_url: 'https://zoom.us/j/existing',
          interviewer_email: 'jordan@example.com',
          interviewer_name: 'Jordan Lee',
        })}
        onClose={() => {}}
      />,
    );
    expect((document.getElementById('m-meeting-url') as HTMLInputElement).value).toBe(
      'https://zoom.us/j/existing',
    );
    expect((document.getElementById('m-email') as HTMLInputElement).value).toBe(
      'jordan@example.com',
    );
    expect((document.getElementById('m-name') as HTMLInputElement).value).toBe('Jordan Lee');
  });
});

describe('ScheduleModal — validation gates', () => {
  function setup() {
    render(
      <ScheduleModal
        id="m"
        reqId="r"
        candidateId="c"
        roundId="round-1"
        existing={makeCandidateRound()}
        onClose={() => {}}
      />,
    );
  }

  test('blocks submit + shows inline error when meeting_url is empty', async () => {
    setup();
    // Date/time are auto-filled by the modal's default; we just need to
    // submit without typing a URL.
    fireEvent.submit(document.getElementById('m-form') as HTMLFormElement);
    // Wait one tick for setError.
    await new Promise((r) => setTimeout(r, 0));
    const err = document.getElementById('m-error');
    expect(err?.textContent).toMatch(/Meeting URL is required/i);
    expect(captured.schedule).toHaveLength(0);
  });

  test('blocks submit + shows inline error when interviewer email is malformed', async () => {
    setup();
    fireEvent.change(document.getElementById('m-meeting-url') as HTMLInputElement, {
      target: { value: 'https://zoom.us/j/12345' },
    });
    fireEvent.change(document.getElementById('m-email') as HTMLInputElement, {
      target: { value: 'definitely-not-an-email' },
    });
    fireEvent.submit(document.getElementById('m-form') as HTMLFormElement);
    await new Promise((r) => setTimeout(r, 0));
    const err = document.getElementById('m-error');
    expect(err?.textContent).toMatch(/interviewer email looks invalid/i);
    expect(captured.schedule).toHaveLength(0);
  });

  test('blocks submit when the date is in the far past (>5 min)', async () => {
    setup();
    fireEvent.change(document.getElementById('m-date') as HTMLInputElement, {
      target: { value: '2020-01-01' },
    });
    fireEvent.change(document.getElementById('m-time') as HTMLInputElement, {
      target: { value: '10:00' },
    });
    fireEvent.change(document.getElementById('m-meeting-url') as HTMLInputElement, {
      target: { value: 'https://zoom.us/j/12345' },
    });
    fireEvent.submit(document.getElementById('m-form') as HTMLFormElement);
    await new Promise((r) => setTimeout(r, 0));
    expect(document.getElementById('m-error')?.textContent).toMatch(
      /Pick a date\/time in the future/,
    );
    expect(captured.schedule).toHaveLength(0);
  });
});

describe('ScheduleModal — submit pipeline', () => {
  test('submits with ISO-with-offset scheduled_at + scheduling_timezone', async () => {
    let closed = false;
    render(
      <ScheduleModal
        id="m"
        reqId="r1"
        candidateId="c1"
        roundId="round-1"
        existing={makeCandidateRound({ id: 'cr-abc' })}
        onClose={() => {
          closed = true;
        }}
      />,
    );

    // Set date 1 day in the future to avoid past-time auto-bumping.
    const tomorrow = new Date(Date.now() + 86_400_000);
    const isoDate = tomorrow.toISOString().slice(0, 10);
    fireEvent.change(document.getElementById('m-date') as HTMLInputElement, {
      target: { value: isoDate },
    });
    fireEvent.change(document.getElementById('m-time') as HTMLInputElement, {
      target: { value: '15:00' },
    });
    // Force NY tz via the underlying <select>.
    const tzSelect = document.getElementById('m-timezone') as HTMLSelectElement;
    fireEvent.change(tzSelect, { target: { value: 'America/New_York' } });
    fireEvent.change(document.getElementById('m-meeting-url') as HTMLInputElement, {
      target: { value: 'https://zoom.us/j/abc' },
    });
    fireEvent.submit(document.getElementById('m-form') as HTMLFormElement);

    // Let the async submit resolve.
    await new Promise((r) => setTimeout(r, 5));

    expect(captured.schedule).toHaveLength(1);
    const [reqId, candidateId, roundId, payload, opts] = captured.schedule[0] as [
      string,
      string,
      string,
      Record<string, string>,
      { crId: string },
    ];
    expect(reqId).toBe('r1');
    expect(candidateId).toBe('c1');
    expect(roundId).toBe('round-1');
    expect(opts.crId).toBe('cr-abc');
    expect(payload.scheduling_timezone).toBe('America/New_York');
    // The wall-clock 15:00 in NY → -04:00 (EDT) or -05:00 (EST). The FE
    // MUST send the offset, not a naive ISO.
    expect(payload.scheduled_at).toMatch(/^\d{4}-\d{2}-\d{2}T15:00:00-0[45]:00$/);
    expect(payload.meeting_url).toBe('https://zoom.us/j/abc');
    // Email + name were left blank → not in payload at all.
    expect(payload.interviewer_email).toBeUndefined();
    expect(payload.interviewer_name).toBeUndefined();
    // onClose runs after a successful submit.
    expect(closed).toBe(true);
  });

  test('routes to interviews.reschedule when existing status is "scheduled"', async () => {
    render(
      <ScheduleModal
        id="m"
        reqId="r"
        candidateId="c"
        roundId="round-1"
        existing={makeCandidateRound({
          status: 'scheduled',
          scheduled_at: '2026-06-01T19:00:00+00:00',
          scheduling_timezone: 'America/New_York',
          meeting_url: 'https://zoom.us/j/existing',
          interviewer_email: 'jordan@example.com',
        })}
        onClose={() => {}}
      />,
    );

    // Bump the date to ensure we're not auto-rejected as past.
    const tomorrow = new Date(Date.now() + 86_400_000);
    fireEvent.change(document.getElementById('m-date') as HTMLInputElement, {
      target: { value: tomorrow.toISOString().slice(0, 10) },
    });
    fireEvent.submit(document.getElementById('m-form') as HTMLFormElement);
    await new Promise((r) => setTimeout(r, 5));

    expect(captured.reschedule).toHaveLength(1);
    expect(captured.schedule).toHaveLength(0);
  });

  test('omits interviewer_email + interviewer_name when blank', async () => {
    render(
      <ScheduleModal
        id="m"
        reqId="r"
        candidateId="c"
        roundId="round-1"
        existing={makeCandidateRound()}
        onClose={() => {}}
      />,
    );
    const tomorrow = new Date(Date.now() + 86_400_000);
    fireEvent.change(document.getElementById('m-date') as HTMLInputElement, {
      target: { value: tomorrow.toISOString().slice(0, 10) },
    });
    fireEvent.change(document.getElementById('m-meeting-url') as HTMLInputElement, {
      target: { value: 'https://zoom.us/j/12345' },
    });
    fireEvent.submit(document.getElementById('m-form') as HTMLFormElement);
    await new Promise((r) => setTimeout(r, 5));

    expect(captured.schedule).toHaveLength(1);
    const payload = (captured.schedule[0] as unknown[])[3] as Record<string, unknown>;
    expect('interviewer_email' in payload).toBe(false);
    expect('interviewer_name' in payload).toBe(false);
    expect(payload.meeting_url).toBe('https://zoom.us/j/12345');
  });
});

describe('ScheduleModal — AI-hosted branch', () => {
  test('non-platform round still renders the human schedule form (meeting URL field present)', () => {
    render(
      <ScheduleModal
        id="m"
        reqId="r"
        candidateId="c"
        roundId="round-1"
        existing={makeCandidateRound()}
        onClose={() => {}}
      />,
    );
    // The human form's meeting-URL input is present; the OpenRecruiting send-link block is not.
    expect(document.getElementById('m-meeting-url')).not.toBeNull();
    expect(document.getElementById('m-openrecruiting')).toBeNull();
  });

  test('AI-hosted round shows "Send screening link" (no meeting-URL form)', () => {
    render(
      <ScheduleModal
        id="m"
        reqId="r"
        candidateId="c"
        roundId="round-1"
        existing={makeCandidateRound({ id: 'cr-scout' })}
        aiHosted
        onClose={() => {}}
      />,
    );
    // The OpenRecruiting branch renders the send-link block, NOT the human schedule form.
    expect(document.getElementById('m-openrecruiting')).not.toBeNull();
    expect(document.getElementById('m-meeting-url')).toBeNull();
    expect(document.getElementById('m-date')).toBeNull();
    expect(document.getElementById('m-email')).toBeNull();
    const submit = document.getElementById('m-submit') as HTMLButtonElement;
    expect(submit.textContent?.trim()).toMatch(/Send screening link/i);
  });

  test('clicking "Send screening link" calls inviteCandidateRound + shows the copy link', async () => {
    inviteCrSpy = spyOn(screeningModule, 'inviteCandidateRound').mockResolvedValue({
      token: 'tok-xyz',
      expiresAt: '2030-01-01T00:00:00Z',
      verifyUrl: 'http://localhost:3005/screening/tok-xyz/verify',
      validityDays: 9,
    });

    render(
      <ScheduleModal
        id="m"
        reqId="r"
        candidateId="c"
        roundId="round-1"
        existing={makeCandidateRound({ id: 'cr-scout-2' })}
        aiHosted
        onClose={() => {}}
      />,
    );

    fireEvent.click(document.getElementById('m-submit') as HTMLButtonElement);
    await new Promise((r) => setTimeout(r, 5));

    // The per-candidate-round invite endpoint was called with the candidate_round id.
    expect(inviteCrSpy).toHaveBeenCalledTimes(1);
    expect(inviteCrSpy.mock.calls[0]?.[0]).toBe('cr-scout-2');

    // Success state surfaces the verify link + validity window for copy-sharing.
    const link = document.getElementById('m-link') as HTMLInputElement;
    expect(link.value).toBe('http://localhost:3005/screening/tok-xyz/verify');
    expect(document.getElementById('m-success')?.textContent).toMatch(/9 days/);
    expect(document.getElementById('m-copy')).not.toBeNull();
  });
});
