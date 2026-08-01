'use client';

import { cn } from '@/lib/utils';

const FALLBACK_TIMEZONES = [
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Anchorage',
  'Pacific/Honolulu',
  'Europe/London',
  'Europe/Paris',
  'Europe/Berlin',
  'Asia/Dubai',
  'Asia/Kolkata',
  'Asia/Singapore',
  'Asia/Tokyo',
  'Australia/Sydney',
  'UTC',
];

const TIMEZONE_OPTIONS: string[] = (() => {
  try {
    const intlWithSupported = Intl as typeof Intl & {
      supportedValuesOf?: (key: string) => string[];
    };
    if (typeof intlWithSupported.supportedValuesOf === 'function') {
      return intlWithSupported.supportedValuesOf('timeZone');
    }
  } catch {
    // fall through
  }
  return FALLBACK_TIMEZONES;
})();

function formatTzLabel(tz: string): string {
  const parts = tz.split('/');
  const city = (parts[parts.length - 1] || tz).replace(/_/g, ' ');
  const region = parts[0] || '';
  try {
    const offset =
      new Intl.DateTimeFormat('en-US', {
        timeZone: tz,
        timeZoneName: 'shortOffset',
      })
        .formatToParts(new Date())
        .find((p) => p.type === 'timeZoneName')?.value || '';
    return `${city} (${offset})${region ? ` — ${region}` : ''}`;
  } catch {
    return tz.replace(/_/g, ' ');
  }
}

const LABEL_CACHE = new Map<string, string>();
function getLabel(tz: string): string {
  let label = LABEL_CACHE.get(tz);
  if (!label) {
    label = formatTzLabel(tz);
    LABEL_CACHE.set(tz, label);
  }
  return label;
}

interface TimezoneSelectProps {
  id: string;
  value: string;
  onChange: (value: string) => void;
  className?: string;
}

export function TimezoneSelect({ id, value, onChange, className }: TimezoneSelectProps) {
  const valueInList = TIMEZONE_OPTIONS.includes(value);

  return (
    <select
      id={id}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={cn(
        'rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary focus:border-text-primary focus:outline-none',
        className,
      )}
    >
      {!valueInList && value && <option value={value}>{getLabel(value)}</option>}
      {TIMEZONE_OPTIONS.map((tz) => (
        <option key={tz} value={tz}>
          {getLabel(tz)}
        </option>
      ))}
    </select>
  );
}
