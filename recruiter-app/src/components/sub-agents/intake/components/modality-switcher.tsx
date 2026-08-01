'use client';

import { useModalitySwitch } from '@/hooks/intake/use-modality-switch';
import type { IntakeModality } from '@/types/intake';

interface Props {
  currentModality: IntakeModality | null;
}

export function ModalitySwitcher({ currentModality }: Props) {
  const { switchTo, isSwitching } = useModalitySwitch();
  const showChat = currentModality !== 'text';
  const showCall = currentModality !== 'voice';
  const switchingText = isSwitching === 'text';
  const switchingVoice = isSwitching === 'voice';
  const disabled = switchingText || switchingVoice;

  return (
    <div
      id="v2-intake-modality-switcher"
      data-testid="v2-intake-modality-switcher"
      className="inline-flex items-center gap-2 rounded-full p-1"
      role="group"
      aria-label="Switch conversation mode"
      style={{ background: 'var(--app-secondary)', border: '1px solid var(--app-border)' }}
    >
      {showChat && (
        <button
          id="v2-intake-switch-to-chat"
          data-testid="v2-intake-switch-to-chat"
          type="button"
          onClick={() => void switchTo('text')}
          disabled={disabled}
          className="inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-xs font-medium uppercase tracking-wide transition disabled:opacity-50 disabled:cursor-not-allowed"
          style={{ color: 'var(--text-secondary)' }}
        >
          {switchingText && (
            <span
              id="v2-intake-switch-to-chat-spinner"
              data-testid="v2-intake-switch-to-chat-spinner"
              className="inline-block h-3 w-3 rounded-full border-2 border-t-transparent animate-spin"
              aria-hidden="true"
              style={{ borderColor: 'var(--text-muted)', borderTopColor: 'transparent' }}
            />
          )}
          {switchingText ? 'Switching to chat...' : 'Switch to chat'}
        </button>
      )}
      {showCall && (
        <button
          id="v2-intake-switch-to-call"
          data-testid="v2-intake-switch-to-call"
          type="button"
          onClick={() => void switchTo('voice')}
          disabled={disabled}
          className="inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-xs font-medium uppercase tracking-wide transition disabled:opacity-50 disabled:cursor-not-allowed"
          style={{ color: 'var(--cortex-500)' }}
        >
          {switchingVoice && (
            <span
              id="v2-intake-switch-to-call-spinner"
              data-testid="v2-intake-switch-to-call-spinner"
              className="inline-block h-3 w-3 rounded-full border-2 border-t-transparent animate-spin"
              aria-hidden="true"
              style={{ borderColor: 'var(--cortex-500)', borderTopColor: 'transparent' }}
            />
          )}
          {switchingVoice ? 'Switching to call...' : 'Switch to call'}
        </button>
      )}
    </div>
  );
}
