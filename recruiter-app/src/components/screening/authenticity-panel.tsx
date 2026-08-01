'use client';

import { Info, ShieldAlert, ShieldCheck, ShieldQuestion } from 'lucide-react';
import type {
  AuthenticityLevel,
  AuthenticityOverall,
  AuthenticitySignalKind,
  AuthenticitySignals,
} from '@/domain/candidate';
import { cn } from '@/lib/utils';

// Recruiter-facing panel for the structured screening authenticity signals
// (candidate_rounds.authenticity_signals, migration 117). Product stance:
// DIRECTIONAL signal, never a pass/fail gate — the disclaimer is mandatory.
// Purely presentational: it receives the already-fetched signals object; it does
// no fetching. Renders nothing when signals are absent.

const OVERALL_STYLE: Record<
  AuthenticityOverall,
  { label: string; chip: string; icon: React.ReactNode }
> = {
  likely_authentic: {
    label: 'Likely authentic',
    chip: 'border-[#A7F3D0] bg-[#ECFDF5] text-[#047857]',
    icon: <ShieldCheck strokeWidth={1.75} className="h-3.5 w-3.5" />,
  },
  some_concern: {
    label: 'Some concern',
    chip: 'border-[#FDE68A] bg-[#FFFBEB] text-[#B45309]',
    icon: <ShieldQuestion strokeWidth={1.75} className="h-3.5 w-3.5" />,
  },
  high_concern: {
    label: 'High concern',
    chip: 'border-[#FECACA] bg-[#FEF2F2] text-[#B91C1C]',
    icon: <ShieldAlert strokeWidth={1.75} className="h-3.5 w-3.5" />,
  },
};

const KIND_LABEL: Record<AuthenticitySignalKind, string> = {
  specificity: 'Specificity',
  consistency: 'Consistency',
  read_aloud: 'Read aloud',
};

const LEVEL_LABEL: Record<AuthenticityLevel, string> = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
};

const LEVEL_STYLE: Record<AuthenticityLevel, string> = {
  low: 'border-border bg-surface text-text-muted',
  medium: 'border-[#FDE68A] bg-[#FFFBEB] text-[#B45309]',
  high: 'border-[#FECACA] bg-[#FEF2F2] text-[#B91C1C]',
};

export function AuthenticityPanel({
  id,
  signals,
}: {
  id: string;
  signals: AuthenticitySignals | null | undefined;
}) {
  if (!signals) return null;

  const overall = OVERALL_STYLE[signals.overall] ?? OVERALL_STYLE.likely_authentic;
  const confidencePct = Math.round(Math.max(0, Math.min(1, signals.confidence)) * 100);

  return (
    <section
      id={id}
      aria-label="Candidate authenticity signals"
      className="rounded-[16px] border border-border bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)] print:break-inside-avoid print:shadow-none"
    >
      <header className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span
            aria-hidden
            className="flex h-6 w-6 items-center justify-center rounded-full bg-surface text-text-muted"
          >
            <ShieldCheck strokeWidth={1.75} className="h-3.5 w-3.5" />
          </span>
          <h3 className="font-display text-[20px] text-text-primary leading-tight tracking-[-0.005em]">
            Authenticity signals
          </h3>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.18em]">
            Overall · {confidencePct}% conf.
          </span>
          <span
            id={`${id}-overall`}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium font-sans text-[12px]',
              overall.chip,
            )}
          >
            {overall.icon}
            {overall.label}
          </span>
        </div>
      </header>

      {signals.summary && (
        <p id={`${id}-summary`} className="mb-4 text-[13.5px] text-text-secondary leading-[1.6]">
          {signals.summary}
        </p>
      )}

      {signals.signals.length > 0 && (
        <ul id={`${id}-list`} className="flex flex-col gap-2">
          {signals.signals.map((sig, i) => (
            <li
              // biome-ignore lint/suspicious/noArrayIndexKey: authored signal list is a stable, ordered set per round
              key={i}
              id={`${id}-signal-${i}`}
              className="rounded-[10px] border border-border bg-surface/40 px-4 py-3"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-[13px] text-text-primary">
                  {KIND_LABEL[sig.kind] ?? sig.kind}
                </span>
                <span
                  className={cn(
                    'inline-flex items-center rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em]',
                    LEVEL_STYLE[sig.level] ?? LEVEL_STYLE.low,
                  )}
                >
                  {LEVEL_LABEL[sig.level] ?? sig.level}
                </span>
              </div>
              {sig.note && (
                <p className="mt-1.5 text-[12.5px] text-text-secondary leading-[1.55]">
                  {sig.note}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}

      <div
        id={`${id}-disclaimer`}
        className="mt-4 flex items-start gap-2 rounded-[10px] border border-border border-dashed bg-surface/30 px-3.5 py-2.5"
      >
        <Info
          aria-hidden
          strokeWidth={1.75}
          className="mt-0.5 h-3.5 w-3.5 shrink-0 text-text-faint"
        />
        <p className="text-[11.5px] text-text-muted leading-[1.5]">
          Directional signal — not a pass/fail gate. These observations come from the interview text
          and may misread non-native speakers or nervous candidates. Use them only as a prompt to
          look closer, never as a decision on their own.
        </p>
      </div>
    </section>
  );
}
