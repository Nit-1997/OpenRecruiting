'use client';

import { X } from 'lucide-react';
import { useState } from 'react';
import { cn } from '@/lib/utils';
import { candidates } from '@/services';
import { ServiceError } from '@/services/service-error';

interface AddCandidateFormProps {
  id: string;
  roleId: string;
  onClose: () => void;
}

export function AddCandidateForm({ id, roleId, onClose }: AddCandidateFormProps) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [requestId, setRequestId] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    setRequestId(null);
    try {
      await candidates.create(roleId, { name, email });
      onClose();
    } catch (err) {
      // Copy policy:
      //  - 'validation' / 'conflict' / 'forbidden' / 'not_found': backend
      //    detail is user-facing and field-specific — show it verbatim.
      //  - 'internal' (5xx): backend detail is implementation noise —
      //    show a contextual form-level message instead.
      //  - non-ServiceError throw (network blip, bug): contextual copy.
      if (err instanceof ServiceError) {
        setError(
          err.code === 'internal'
            ? "Couldn't add candidate. Please try again."
            : err.message,
        );
        setRequestId(err.requestId ?? null);
      } else {
        setError("Couldn't add candidate. Please try again.");
        setRequestId(null);
      }
      setBusy(false);
    }
  };

  return (
    <div
      id={id}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
    >
      <form
        onSubmit={submit}
        className="w-full max-w-md rounded-[16px] border border-border bg-white p-6 shadow-[0_20px_60px_rgba(0,0,0,0.2)]"
      >
        <div className="mb-4 flex items-start justify-between gap-2">
          <h2 className="font-display text-[22px] text-text-primary leading-tight">
            Add candidate
          </h2>
          <button
            id={`${id}-close`}
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-full text-text-muted hover:text-text-primary"
          >
            <X strokeWidth={1.75} className="h-4 w-4" />
          </button>
        </div>
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
              Name
            </span>
            <input
              id={`${id}-name`}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Ada Lovelace"
              className="rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary placeholder:text-text-muted focus:border-text-primary focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
              Email
            </span>
            <input
              id={`${id}-email`}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="ada@example.com"
              className="rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary placeholder:text-text-muted focus:border-text-primary focus:outline-none"
            />
          </label>
        </div>
        {error && (
          <p id={`${id}-error`} className="mt-3 text-[#B91C1C] text-[12.5px]">
            {error}
            {requestId && (
              <span className="ml-1 font-mono text-text-faint">
                (ref: {requestId.slice(0, 8)})
              </span>
            )}
          </p>
        )}
        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            id={`${id}-cancel`}
            type="button"
            onClick={onClose}
            className="rounded-full border border-border bg-white px-3.5 py-2 text-[13px] text-text-primary hover:border-text-primary"
          >
            Cancel
          </button>
          <button
            id={`${id}-submit`}
            type="submit"
            disabled={!name.trim() || !email.trim() || busy}
            className={cn(
              'rounded-full px-3.5 py-2 font-medium text-[13px] transition-colors',
              name.trim() && email.trim() && !busy
                ? 'border border-text-primary bg-text-primary text-white hover:bg-[#222]'
                : 'cursor-not-allowed border border-border bg-surface text-text-faint',
            )}
          >
            {busy ? 'Adding…' : 'Add candidate'}
          </button>
        </div>
      </form>
    </div>
  );
}
