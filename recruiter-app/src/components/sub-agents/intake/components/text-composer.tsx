'use client';

import { ArrowUp } from 'lucide-react';
import { type FormEvent, type KeyboardEvent, useState } from 'react';

interface Props {
  /** Returns false when the send was dropped/failed — the draft is then kept so
   *  the recruiter never loses what they typed. */
  onSend: (message: string) => boolean | void | Promise<boolean | void>;
  disabled: boolean;
  placeholder?: string;
}

export function TextComposer({
  onSend,
  disabled,
  placeholder = 'Type your reply… (Enter to send, Shift+Enter for newline)',
}: Props) {
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const isEmpty = !draft.trim();

  async function handleSubmit(e?: FormEvent) {
    e?.preventDefault();
    if (disabled || sending || isEmpty) return;
    const msg = draft.trim();
    // Clear optimistically for a snappy feel, but restore the text if the send
    // is dropped/failed (e.g. a modality-switch race) so it's never lost.
    setDraft('');
    setSending(true);
    try {
      const ok = await onSend(msg);
      if (ok === false) setDraft((cur) => (cur ? cur : msg));
    } finally {
      setSending(false);
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }

  return (
    <form id="v2-intake-text-composer-form" onSubmit={handleSubmit} className="mz-conv-input">
      <textarea
        id="v2-intake-text-composer-input"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={handleKeyDown}
        rows={3}
        placeholder={placeholder}
        disabled={disabled}
        style={{ opacity: disabled ? 0.6 : 1 }}
      />
      <button
        id="v2-intake-text-composer-send"
        type="submit"
        disabled={disabled || isEmpty}
        className="mz-round-btn mz-round-send"
        aria-label="Send"
      >
        <ArrowUp size={15} color="currentColor" />
      </button>
    </form>
  );
}
