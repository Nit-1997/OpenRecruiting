'use client';

import { useState } from 'react';
import { useVoiceCall } from '@/hooks/intake/use-voice-call';
import { useIntakeStore } from '@/stores/intake-store';
import { switchModality, IntakeApiError } from '@/lib/intake/api';
import type { IntakeSession } from '@/types/intake';

interface Props {
  session: IntakeSession;
}

export function VoiceReconnectStage({ session }: Props) {
  const { start } = useVoiceCall(session.id);
  const setPendingTransition = useIntakeStore((s) => s.setPendingTransition);
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSwitchToChat() {
    setSwitching(true);
    setError(null);
    try {
      await switchModality(session.id, 'text');
      setPendingTransition('text_active', 60_000);
    } catch (e) {
      if (e instanceof IntakeApiError && e.code === 'modality_conflict') {
        setError('Another mode is currently active — try refreshing.');
      } else {
        setError(e instanceof Error ? e.message : 'failed to switch to chat');
      }
    } finally {
      setSwitching(false);
    }
  }

  return (
    <div
      id="v2-intake-voice-reconnect-overlay"
      className="fixed inset-0 flex items-center justify-center p-6"
      style={{ background: 'rgba(0, 0, 0, 0.55)', zIndex: 50 }}
    >
      <div
        id="v2-intake-voice-reconnect-modal"
        data-testid="v2-intake-voice-reconnect-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="v2-intake-voice-reconnect-title"
        className="max-w-md w-full rounded-2xl p-6 space-y-4"
        style={{ background: 'var(--app-card)', border: '1px solid var(--app-border)' }}
      >
        <h2
          id="v2-intake-voice-reconnect-title"
          className="text-xl"
          style={{ fontFamily: 'var(--font-display)', color: 'var(--text-primary)' }}
        >
          Voice call was active
        </h2>
        <p
          id="v2-intake-voice-reconnect-body"
          className="text-sm"
          style={{ color: 'var(--text-secondary)' }}
        >
          We saved your conversation. Rejoin the call to keep going, or switch to chat
          to wrap up without speaking.
        </p>
        <div className="flex items-center gap-2 pt-2">
          <button
            id="v2-intake-voice-reconnect-rejoin-btn"
            data-testid="v2-intake-voice-reconnect-rejoin-btn"
            type="button"
            onClick={start}
            disabled={switching}
            className="flex-1 px-4 py-2 rounded-md text-sm text-white font-medium disabled:opacity-50"
            style={{ background: 'var(--cortex-500)' }}
          >
            Rejoin call
          </button>
          <button
            id="v2-intake-voice-reconnect-switch-btn"
            data-testid="v2-intake-voice-reconnect-switch-btn"
            type="button"
            onClick={handleSwitchToChat}
            disabled={switching}
            className="flex-1 px-4 py-2 rounded-md text-sm disabled:opacity-50"
            style={{
              background: 'transparent',
              color: 'var(--text-primary)',
              border: '1px solid var(--app-border)',
            }}
          >
            {switching ? 'Switching...' : 'Switch to chat'}
          </button>
        </div>
        {error && (
          <div
            id="v2-intake-voice-reconnect-error"
            data-testid="v2-intake-voice-reconnect-error"
            className="text-xs"
            style={{ color: 'var(--status-danger-fg)' }}
          >
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
