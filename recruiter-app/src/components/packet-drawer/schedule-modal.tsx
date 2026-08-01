'use client';

import { formatInTimeZone, fromZonedTime } from 'date-fns-tz';
import { Check, Copy } from 'lucide-react';
import { useMemo, useState } from 'react';
import { BrandIcon } from '@/components/icons/brand-icons';
import { TimezoneSelect } from '@/components/ui/timezone-select';
import type { CandidateRound } from '@/domain';
import { cn } from '@/lib/utils';
import { interviews } from '@/services';
import { type CandidateRoundInvite, inviteCandidateRound } from '@/services/screening';
import { ServiceError } from '@/services/service-error';
import { ModalShell } from './drawer';

const EMAIL_RE = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;

// ---------------------------------------------------------------------------
// Pure helper — no React deps so it's easy to unit-test
// ---------------------------------------------------------------------------

interface ScheduleDefault {
  date: string;
  time: string;
  tz: string;
}

/**
 * Default date+time for a fresh Schedule modal — the *current* date and time
 * in the given (or browser) zone. Matches v1's behavior: the picker reflects
 * "now", and the recruiter edits forward. Snapping silently moved the time
 * past where the recruiter expected it.
 */
export function getDefaultSchedule(opts: { now?: Date; tz?: string }): ScheduleDefault {
  const tz = opts.tz ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
  const now = opts.now ?? new Date();
  return {
    date: formatInTimeZone(now, tz, 'yyyy-MM-dd'),
    time: formatInTimeZone(now, tz, 'HH:mm'),
    tz,
  };
}

// ---------------------------------------------------------------------------
// ScheduleModal component
// ---------------------------------------------------------------------------

export function ScheduleModal({
  id,
  reqId,
  candidateId,
  roundId,
  existing,
  aiHosted = false,
  onClose,
}: {
  id: string;
  reqId: string;
  candidateId: string;
  roundId: string;
  existing: CandidateRound;
  // AI-hosted round: scheduling = sending the async screening link, NOT
  // booking a time + human interviewer. Branches to a wholly different flow.
  aiHosted?: boolean;
  onClose: () => void;
}) {
  // For a OpenRecruiting round, "scheduling" sends the candidate the screening link.
  // The human date/time/meeting-URL/interviewer form below is never rendered.
  if (aiHosted) {
    return <SendScreeningLink id={id} candidateRoundId={existing.id} onClose={onClose} />;
  }
  return (
    <HumanScheduleModal
      id={id}
      reqId={reqId}
      candidateId={candidateId}
      roundId={roundId}
      existing={existing}
      onClose={onClose}
    />
  );
}

// ---------------------------------------------------------------------------
// AI-hosted flow — send (or re-send) the candidate the screening link.
// No booked time, no meeting URL, no human interviewer. On success shows the
// verify_url with a copy-link affordance (usable even if email isn't set up
// locally) plus the validity window.
// ---------------------------------------------------------------------------

function SendScreeningLink({
  id,
  candidateRoundId,
  onClose,
}: {
  id: string;
  candidateRoundId: string;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CandidateRoundInvite | null>(null);
  const [copied, setCopied] = useState(false);

  const send = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const invite = await inviteCandidateRound(candidateRoundId);
      setResult(invite);
    } catch (err) {
      setError(err instanceof ServiceError ? err.message : 'Could not send the screening link');
    } finally {
      setBusy(false);
    }
  };

  const copyLink = async () => {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.verifyUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError('Could not copy — select and copy the link manually.');
    }
  };

  const validityLabel = result
    ? result.validityDays === 1
      ? '1 day'
      : `${result.validityDays} days`
    : '';

  return (
    <ModalShell id={id} title="Send screening link" onClose={onClose}>
      <div id={`${id}-openrecruiting`} className="flex flex-col gap-3">
        <div className="flex items-start gap-2 rounded-[10px] border border-cortex-500/30 bg-cortex-500/5 px-3 py-2.5">
          <BrandIcon className="mt-0.5 h-4 w-4 shrink-0 text-cortex-500" />
          <p className="text-[12.5px] text-text-secondary leading-[1.5]">
            OpenRecruiting hosts this round. The candidate gets an async screening link — no meeting time or
            human interviewer. The link stays valid for the round's configured window.
          </p>
        </div>

        {!result && (
          <p className="text-[13px] text-text-muted">
            Send the candidate their screening link now? They can complete it anytime before it
            expires.
          </p>
        )}

        {result && (
          <div id={`${id}-success`} className="flex flex-col gap-2">
            <p className="text-[13px] text-text-primary">
              Screening link sent. Valid for {validityLabel}.
            </p>
            <div className="flex items-stretch gap-2">
              <input
                id={`${id}-link`}
                readOnly
                value={result.verifyUrl}
                className="min-w-0 flex-1 rounded-[10px] border border-border bg-surface px-3 py-2 font-mono text-[11.5px] text-text-secondary focus:border-text-primary focus:outline-none"
              />
              <button
                id={`${id}-copy`}
                type="button"
                onClick={copyLink}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-[10px] border border-text-primary bg-text-primary px-3 py-2 font-medium text-[12px] text-white hover:bg-[#222]"
              >
                {copied ? (
                  <Check strokeWidth={2} className="h-3.5 w-3.5" />
                ) : (
                  <Copy strokeWidth={1.75} className="h-3.5 w-3.5" />
                )}
                {copied ? 'Copied' : 'Copy link'}
              </button>
            </div>
          </div>
        )}

        {error && (
          <p id={`${id}-error`} className="text-[#B91C1C] text-[12.5px]">
            {error}
          </p>
        )}

        <div className="mt-2 flex justify-end gap-2">
          <button
            id={`${id}-cancel`}
            type="button"
            onClick={onClose}
            className="rounded-full border border-border bg-white px-3.5 py-2 text-[13px] text-text-muted hover:border-text-primary hover:text-text-primary"
          >
            {result ? 'Done' : 'Cancel'}
          </button>
          {!result && (
            <button
              id={`${id}-submit`}
              type="button"
              onClick={send}
              disabled={busy}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full px-3.5 py-2 font-medium text-[13px] transition-colors',
                busy
                  ? 'cursor-not-allowed border border-border bg-surface text-text-faint'
                  : 'border border-text-primary bg-text-primary text-white hover:bg-[#222]',
              )}
            >
              <BrandIcon className="h-3.5 w-3.5" />
              {busy ? 'Sending…' : 'Send screening link'}
            </button>
          )}
        </div>
      </div>
    </ModalShell>
  );
}

// ---------------------------------------------------------------------------
// Human (non-platform) scheduling — unchanged date/time/meeting-URL/interviewer
// flow. Extracted verbatim so the OpenRecruiting branch above can short-circuit before
// any of this hook state runs.
// ---------------------------------------------------------------------------

function HumanScheduleModal({
  id,
  reqId,
  candidateId,
  roundId,
  existing,
  onClose,
}: {
  id: string;
  reqId: string;
  candidateId: string;
  roundId: string;
  existing: CandidateRound;
  onClose: () => void;
}) {
  // TZ-aware date/time picker. Mirrors v1's `useScheduling` hook:
  //   - recruiter picks date + time + IANA zone
  //   - we combine locally, convert with `fromZonedTime(local, tz)` →
  //     UTC instant, then emit ISO-8601 with offset via `formatInTimeZone`
  //   - BE persists scheduled_at + scheduling_timezone (migration 88) so a
  //     reschedule re-renders in the same zone the recruiter chose
  const browserTz = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, []);

  const initialPicker = useMemo(() => {
    if (existing.scheduled_at) {
      const tz = existing.scheduling_timezone || browserTz;
      const dt = new Date(existing.scheduled_at);
      return {
        date: formatInTimeZone(dt, tz, 'yyyy-MM-dd'),
        time: formatInTimeZone(dt, tz, 'HH:mm'),
        tz,
      };
    }
    return getDefaultSchedule(
      existing.scheduling_timezone ? { tz: existing.scheduling_timezone } : {},
    );
  }, [existing.scheduled_at, existing.scheduling_timezone, browserTz]);

  const [date, setDate] = useState(initialPicker.date);
  const [time, setTime] = useState(initialPicker.time);
  const [tz, setTz] = useState(initialPicker.tz);
  const [email, setEmail] = useState(existing.interviewer_email ?? '');
  const [name, setName] = useState(existing.interviewer_name ?? '');
  const [meetingUrl, setMeetingUrl] = useState(existing.meeting_url ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (!date) {
        throw new ServiceError('validation', 'Please pick a date.', {
          field: 'scheduled_at',
        });
      }
      if (!time) {
        throw new ServiceError('validation', 'Please pick a time.', {
          field: 'scheduled_at',
        });
      }
      // Guard against a free-typed or empty tz field — `fromZonedTime`
      // silently falls back to UTC for unrecognised strings, which would
      // store the wrong instant. The picker is a proper IANA select, but
      // the empty-string state (controlled component default) is still
      // possible if the recruiter clears it before submit.
      const trimmedTz = tz.trim();
      if (!trimmedTz) {
        throw new ServiceError('validation', 'Please pick a timezone.', {
          field: 'scheduling_timezone',
        });
      }
      const trimmedUrl = meetingUrl.trim();
      if (!trimmedUrl) {
        throw new ServiceError(
          'validation',
          'Meeting URL is required so the interview can be auto-recorded.',
          { field: 'meeting_url' },
        );
      }
      const trimmedEmail = email.trim();
      // interviewer_email is optional — only validate format when supplied.
      if (trimmedEmail && !EMAIL_RE.test(trimmedEmail)) {
        throw new ServiceError('validation', 'That interviewer email looks invalid.', {
          field: 'interviewer_email',
        });
      }
      // Combine YYYY-MM-DD + HH:mm as wall-clock in the chosen zone, then
      // convert to UTC instant. `fromZonedTime` interprets the input string
      // as a time in `tz`; the resulting Date is the UTC instant it
      // represents. `formatInTimeZone` then emits ISO-8601 with the offset
      // for that zone — what the BE Pydantic validator now requires.
      const localStr = `${date}T${time}:00`;
      const utcInstant = fromZonedTime(localStr, trimmedTz);
      if (Number.isNaN(utcInstant.getTime())) {
        throw new ServiceError(
          'validation',
          'That timezone is not recognised. Pick one from the list.',
          { field: 'scheduling_timezone' },
        );
      }
      // The picker defaults to "now" so the recruiter sees the current
      // time on load (cofounder feedback). That means by the moment they
      // submit, the wall-clock instant they picked is several seconds in
      // the past — and the DB-side guard (`schedule_candidate_round` RPC,
      // 60-second grace, migration 87) rejects anything older than that.
      //
      // Reject only obviously-past times (>5 min). For anything within the
      // grace window, bump to "now + 30s" so the RPC's clock check passes
      // regardless of how long the form sat open.
      const nowMs = Date.now();
      if (utcInstant.getTime() < nowMs - 5 * 60_000) {
        throw new ServiceError('validation', 'Pick a date/time in the future.', {
          field: 'scheduled_at',
        });
      }
      let effectiveInstant = utcInstant;
      if (utcInstant.getTime() < nowMs + 30_000) {
        effectiveInstant = new Date(nowMs + 30_000);
      }
      const isoWithOffset = formatInTimeZone(
        effectiveInstant,
        trimmedTz,
        "yyyy-MM-dd'T'HH:mm:ssxxx",
      );
      const trimmedName = name.trim();
      const sharedInput = {
        scheduled_at: isoWithOffset,
        scheduling_timezone: trimmedTz,
        meeting_url: trimmedUrl,
        ...(trimmedEmail ? { interviewer_email: trimmedEmail } : {}),
        ...(trimmedName ? { interviewer_name: trimmedName } : {}),
      };
      if (existing.status === 'scheduled') {
        await interviews.reschedule(reqId, candidateId, roundId, sharedInput, {
          crId: existing.id,
        });
      } else {
        await interviews.schedule(reqId, candidateId, roundId, sharedInput, {
          crId: existing.id,
        });
      }
      onClose();
    } catch (err) {
      setError(err instanceof ServiceError ? err.message : 'Could not schedule interview');
      setBusy(false);
    }
  };

  return (
    <ModalShell id={id} title="Schedule interview" onClose={onClose}>
      <form id={`${id}-form`} onSubmit={submit} className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
              Date
            </span>
            <input
              id={`${id}-date`}
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary focus:border-text-primary focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
              Time
            </span>
            <input
              id={`${id}-time`}
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              className="rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary focus:border-text-primary focus:outline-none"
            />
          </label>
        </div>
        <label htmlFor={`${id}-timezone`} className="flex flex-col gap-1">
          <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
            Timezone
          </span>
          <TimezoneSelect id={`${id}-timezone`} value={tz} onChange={setTz} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
            Meeting URL · required
          </span>
          <input
            id={`${id}-meeting-url`}
            type="url"
            inputMode="url"
            required
            value={meetingUrl}
            onChange={(e) => setMeetingUrl(e.target.value)}
            placeholder="https://zoom.us/j/12345 or https://meet.google.com/abc-defg-hij"
            className="rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary focus:border-text-primary focus:outline-none"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
            Interviewer name · optional
          </span>
          <input
            id={`${id}-name`}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Jordan Lee"
            className="rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary focus:border-text-primary focus:outline-none"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
            Interviewer email · optional
          </span>
          <input
            id={`${id}-email`}
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="jordan@example.com"
            className="rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary focus:border-text-primary focus:outline-none"
          />
        </label>
        {error && (
          <p id={`${id}-error`} className="text-[#B91C1C] text-[12.5px]">
            {error}
          </p>
        )}
        <div className="mt-2 flex justify-end gap-2">
          <button
            id={`${id}-cancel`}
            type="button"
            onClick={onClose}
            className="rounded-full border border-border bg-white px-3.5 py-2 text-[13px] text-text-muted hover:border-text-primary hover:text-text-primary"
          >
            Cancel
          </button>
          <button
            id={`${id}-submit`}
            type="submit"
            disabled={busy}
            className={cn(
              'rounded-full px-3.5 py-2 font-medium text-[13px] transition-colors',
              busy
                ? 'cursor-not-allowed border border-border bg-surface text-text-faint'
                : 'border border-text-primary bg-text-primary text-white hover:bg-[#222]',
            )}
          >
            {busy ? 'Saving…' : existing.status === 'scheduled' ? 'Reschedule' : 'Schedule'}
          </button>
        </div>
      </form>
    </ModalShell>
  );
}
