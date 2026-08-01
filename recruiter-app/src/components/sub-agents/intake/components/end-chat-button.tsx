'use client';

import { useState } from 'react';
import { endConversation } from '@/lib/intake/api';
import { useIntakeStore } from '@/stores/intake-store';
import { useConfirm } from '@/components/ui/confirm-dialog';

interface Props {
  sessionId: string;
  onEnded?: () => void;
}

export function EndChatButton({ sessionId, onEnded }: Props) {
  const [inFlight, setInFlight] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const setEndedSession = useIntakeStore((s) => s.setEndedSession);
  const confirm = useConfirm();

  async function handleClick() {
    if (inFlight) return;
    const ok = await confirm({
      title: 'End this intake chat?',
      body: "You'll be able to review and submit afterward.",
      confirmLabel: 'End chat',
    });
    if (!ok) return;
    setInFlight(true);
    setError(null);
    try {
      await endConversation(sessionId);
      // Persistent client signal — the ONLY thing that moves deriveStage to the
      // wrapping/submit screen. (active_modality going null no longer does.)
      setEndedSession(sessionId);
      onEnded?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed to end chat');
    } finally {
      setInFlight(false);
    }
  }

  return (
    <div id="v2-intake-end-chat-wrapper" className="inline-flex flex-col items-end gap-1">
      <button
        id="v2-intake-end-chat-button"
        type="button"
        onClick={handleClick}
        disabled={inFlight}
        className="text-xs px-3 py-1 rounded disabled:opacity-50 disabled:cursor-not-allowed"
        style={{
          background: 'transparent',
          color: 'var(--text-secondary)',
          border: '1px solid var(--app-border)',
        }}
      >
        {inFlight ? 'Ending...' : 'End chat'}
      </button>
      {error && (
        <div
          id="v2-intake-end-chat-error"
          data-testid="v2-intake-end-chat-error"
          className="text-[11px]"
          style={{ color: 'var(--status-danger-fg)' }}
        >
          {error}
        </div>
      )}
    </div>
  );
}
