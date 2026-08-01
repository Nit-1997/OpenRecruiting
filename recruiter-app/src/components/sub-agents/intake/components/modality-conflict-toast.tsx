'use client';

import { useIntakeStore } from '@/stores/intake-store';

export function ModalityConflictToast() {
  const switchError = useIntakeStore((s) => s.switchError);
  const dismiss = () => useIntakeStore.setState({ switchError: null });

  if (!switchError) return null;

  if (switchError.type === 'conflict') {
    return (
      <div
        id="v2-intake-modality-conflict-toast"
        data-testid="v2-intake-modality-conflict-toast"
        role="alert"
        className="fixed bottom-6 right-6 z-50 max-w-sm rounded-lg px-4 py-3 shadow-xl"
        style={{
          background: 'var(--status-warn-bg)',
          border: '1px solid var(--status-warn-bd)',
          color: 'var(--status-warn-fg)',
        }}
      >
        <div className="flex items-start gap-3">
          <div className="flex-1 text-sm">
            <div className="font-medium">Another mode is currently active</div>
            <div className="mt-1 opacity-80">
              {switchError.held === 'voice'
                ? 'A voice call is running in another tab. End it before switching here.'
                : 'A chat session is open in another tab. End it before switching here.'}
            </div>
          </div>
          <button
            id="v2-intake-modality-conflict-toast-dismiss"
            data-testid="v2-intake-modality-conflict-toast-dismiss"
            type="button"
            onClick={dismiss}
            className="rounded opacity-60 hover:opacity-100"
            aria-label="Dismiss"
          >
            x
          </button>
        </div>
      </div>
    );
  }

  if (switchError.type === 'drain_failed') {
    return (
      <div
        id="v2-intake-drain-failed-banner"
        data-testid="v2-intake-drain-failed-banner"
        role="alert"
        className="mb-3 rounded px-4 py-3 text-sm"
        style={{
          background: 'var(--status-danger-bg)',
          border: '1px solid var(--status-danger-bd)',
          color: 'var(--status-danger-fg)',
        }}
      >
        <div className="font-medium">Couldn&apos;t end the voice call cleanly.</div>
        <div className="mt-1 opacity-80">
          {switchError.message} Try again, or close this tab and resume from the intake history.
        </div>
        <button
          id="v2-intake-drain-failed-banner-dismiss"
          data-testid="v2-intake-drain-failed-banner-dismiss"
          type="button"
          onClick={dismiss}
          className="mt-2 rounded border px-3 py-1 text-xs"
          style={{ borderColor: 'var(--status-danger-bd)' }}
        >
          Dismiss
        </button>
      </div>
    );
  }

  return (
    <div
      id="v2-intake-modality-generic-error"
      data-testid="v2-intake-modality-generic-error"
      role="alert"
      className="mb-3 rounded px-4 py-3 text-sm"
      style={{
        background: 'var(--app-card)',
        border: '1px solid var(--app-border)',
        color: 'var(--text-primary)',
      }}
    >
      <div>{switchError.message}</div>
      <button
        id="v2-intake-modality-generic-error-dismiss"
        type="button"
        onClick={dismiss}
        className="mt-2 text-xs underline"
        style={{ color: 'var(--text-secondary)' }}
      >
        Dismiss
      </button>
    </div>
  );
}
