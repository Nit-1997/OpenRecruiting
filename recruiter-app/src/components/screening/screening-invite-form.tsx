'use client';

import { Mail, Send } from 'lucide-react';
import { useState } from 'react';

export type InviteMode = 'emails' | 'scope';

export interface ScreeningInviteFormProps {
  id: string;
  /** Validity window surfaced in the helper text + success summary. */
  validityDays: number;
  /** Label for the "all resume-passed" scope choice (config.deployScope). */
  deployScopeLabel: string;
  /** Disabled until the screening agent is attached to the round. */
  disabled?: boolean;
  busy?: boolean;
  /** Last successful invite summary, owned by the parent (null = none yet). */
  lastResult?: { count: number; validityDays: number } | null;
  onSend: (args: { mode: InviteMode; emails: string[] }) => void;
}

// Split on comma / newline / whitespace, trim, drop empties.
function parseEmails(raw: string): string[] {
  return raw
    .split(/[\s,;]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

export function ScreeningInviteForm({
  id,
  validityDays,
  deployScopeLabel,
  disabled = false,
  busy = false,
  lastResult = null,
  onSend,
}: ScreeningInviteFormProps) {
  const [mode, setMode] = useState<InviteMode>('emails');
  const [emailsRaw, setEmailsRaw] = useState('');

  const emails = parseEmails(emailsRaw);
  const canSend = !disabled && !busy && (mode === 'scope' || emails.length > 0);

  return (
    <section id={id} className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
          Invite candidates
        </span>
        <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
          Links valid {validityDays} days
        </span>
      </div>

      <div id={`${id}-modes`} className="flex gap-1 rounded-[10px] bg-surface p-1">
        <button
          id={`${id}-mode-emails`}
          type="button"
          aria-pressed={mode === 'emails'}
          onClick={() => setMode('emails')}
          className={`flex-1 rounded-[8px] px-3 py-1.5 font-medium font-sans text-[12px] transition ${
            mode === 'emails'
              ? 'bg-white text-text-primary shadow-[0_1px_3px_rgba(0,0,0,0.04)]'
              : 'text-text-muted hover:text-text-primary'
          }`}
        >
          Specific emails
        </button>
        <button
          id={`${id}-mode-scope`}
          type="button"
          aria-pressed={mode === 'scope'}
          onClick={() => setMode('scope')}
          className={`flex-1 rounded-[8px] px-3 py-1.5 font-medium font-sans text-[12px] transition ${
            mode === 'scope'
              ? 'bg-white text-text-primary shadow-[0_1px_3px_rgba(0,0,0,0.04)]'
              : 'text-text-muted hover:text-text-primary'
          }`}
        >
          {deployScopeLabel}
        </button>
      </div>

      {mode === 'emails' ? (
        <label className="flex flex-col gap-1" htmlFor={`${id}-emails`}>
          <span className="font-mono text-[9.5px] text-text-faint uppercase tracking-[0.14em]">
            Candidate emails
          </span>
          <textarea
            id={`${id}-emails`}
            value={emailsRaw}
            onChange={(e) => setEmailsRaw(e.target.value)}
            disabled={disabled}
            rows={3}
            placeholder="Comma- or newline-separated, e.g. jordan@acme.com, sam@acme.com"
            className="resize-y rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary placeholder:text-text-muted focus:border-cortex-500 focus:outline-none disabled:opacity-50"
          />
          {emails.length > 0 && (
            <span
              id={`${id}-emails-count`}
              className="font-mono text-[10px] text-text-muted uppercase tracking-[0.14em]"
            >
              {emails.length} recipient{emails.length === 1 ? '' : 's'}
            </span>
          )}
        </label>
      ) : (
        <p
          id={`${id}-scope-note`}
          className="rounded-[10px] border border-border border-dashed bg-surface/40 px-3 py-2.5 text-[12.5px] text-text-muted"
        >
          Sends a screening invite to every candidate matching “{deployScopeLabel}”. Each gets a
          unique link valid {validityDays} days.
        </p>
      )}

      {lastResult && (
        <p
          id={`${id}-result`}
          role="status"
          className="flex items-center gap-1.5 rounded-[10px] border border-[#A7F3D0] bg-[#ECFDF5] px-3 py-2 text-[#047857] text-[12.5px]"
        >
          <Mail strokeWidth={1.75} className="h-3.5 w-3.5" />
          Invited {lastResult.count} candidate{lastResult.count === 1 ? '' : 's'} · links valid{' '}
          {lastResult.validityDays} days.
        </p>
      )}

      <div className="flex justify-end">
        <button
          id={`${id}-send`}
          type="button"
          disabled={!canSend}
          onClick={() => onSend({ mode, emails })}
          className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 font-medium font-sans text-[12.5px] transition ${
            canSend
              ? 'bg-text-primary text-bg hover:opacity-90'
              : 'cursor-not-allowed border border-border bg-surface text-text-faint'
          }`}
        >
          <Send strokeWidth={1.75} className="h-3.5 w-3.5" />
          {busy ? 'Sending…' : 'Send invites'}
        </button>
      </div>
    </section>
  );
}
