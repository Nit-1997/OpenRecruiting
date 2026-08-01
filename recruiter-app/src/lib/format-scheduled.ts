import { formatInTimeZone } from 'date-fns-tz';

function browserTz(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return 'UTC';
  }
}

function resolveTz(tz: string | null | undefined): string {
  const trimmed = tz?.trim();
  if (trimmed) return trimmed;
  return browserTz();
}

function shortOffset(tz: string, instant: Date): string {
  try {
    return (
      new Intl.DateTimeFormat('en-US', { timeZone: tz, timeZoneName: 'shortOffset' })
        .formatToParts(instant)
        .find((p) => p.type === 'timeZoneName')?.value ?? ''
    );
  } catch {
    return '';
  }
}

function safeFormat(
  isoOrInstant: string | Date | null | undefined,
  tz: string,
  pattern: string,
): string | null {
  if (isoOrInstant == null) return null;
  const dt = typeof isoOrInstant === 'string' ? new Date(isoOrInstant) : isoOrInstant;
  if (Number.isNaN(dt.getTime())) return null;
  try {
    return formatInTimeZone(dt, tz, pattern);
  } catch {
    return null;
  }
}

/**
 * Render a scheduled timestamp in the recruiter's saved scheduling_timezone.
 *
 * The browser-local `toLocaleString` family shows the time in the *viewer's*
 * zone — so a recruiter who scheduled "3 PM ET" from a laptop in LA would see
 * "12 PM" everywhere, looking like the interview moved. This helper formats
 * in the saved IANA zone (falling back to browser zone when none is saved)
 * and appends the short offset so the zone is obvious.
 */
export function formatScheduledDate(
  isoOrInstant: string | Date | null | undefined,
  schedulingTimezone: string | null | undefined,
  pattern = 'MMM d',
): string {
  const tz = resolveTz(schedulingTimezone);
  return safeFormat(isoOrInstant, tz, pattern) ?? '';
}

function toInstant(value: string | Date): Date {
  return typeof value === 'string' ? new Date(value) : value;
}

export function formatScheduledDateTime(
  isoOrInstant: string | Date | null | undefined,
  schedulingTimezone: string | null | undefined,
  pattern = "EEE, MMM d 'at' h:mm a",
): string {
  if (isoOrInstant == null) return '';
  const tz = resolveTz(schedulingTimezone);
  const formatted = safeFormat(isoOrInstant, tz, pattern);
  if (!formatted) return '';
  const offset = shortOffset(tz, toInstant(isoOrInstant));
  return offset ? `${formatted} ${offset}` : formatted;
}

export function formatScheduledTime(
  isoOrInstant: string | Date | null | undefined,
  schedulingTimezone: string | null | undefined,
  pattern = 'h:mm a',
): string {
  if (isoOrInstant == null) return '';
  const tz = resolveTz(schedulingTimezone);
  const formatted = safeFormat(isoOrInstant, tz, pattern);
  if (!formatted) return '';
  const offset = shortOffset(tz, toInstant(isoOrInstant));
  return offset ? `${formatted} ${offset}` : formatted;
}
