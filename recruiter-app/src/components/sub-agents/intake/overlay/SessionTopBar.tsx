'use client';
import { ArrowLeft } from 'lucide-react';
import { useRouter } from 'next/navigation';
import type { IntakeSession } from '@/types/intake';

interface Props {
  session: IntakeSession;
  onSubmit?(): void;
  submitDisabled?: boolean;
  submitLabel?: string;
}

export function SessionTopBar({ session, onSubmit, submitDisabled, submitLabel }: Props) {
  const router = useRouter();
  const { role_name, experience_min, experience_max } = session.form_data;

  return (
    <header
      id="intake-session-topbar"
      className="sticky top-0 z-30 flex items-center gap-4 px-4 py-3"
      style={{ borderBottom: '1px solid var(--border)', background: 'var(--surface)' }}
    >
      <button
        id="intake-session-back"
        type="button"
        aria-label="Back to lobby"
        className="mz-icon-btn"
        onClick={() => router.push('/intake')}
      >
        <ArrowLeft className="h-4 w-4" />
      </button>
      <div className="flex min-w-0 flex-1 flex-col">
        <span id="intake-session-eyebrow" className="mz-eyebrow">
          {experience_min}–{experience_max} yrs
        </span>
        <h1 id="intake-session-title" className="mz-h-title truncate">
          {role_name}
        </h1>
      </div>
      {onSubmit && (
        <button
          id="intake-session-submit"
          type="button"
          className="mz-btn-dark"
          onClick={onSubmit}
          disabled={submitDisabled}
        >
          {submitLabel ?? 'Submit intake'}
        </button>
      )}
    </header>
  );
}
