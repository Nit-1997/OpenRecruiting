import { beforeEach, describe, expect, it, mock } from 'bun:test';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ConfirmDialogProvider } from '@/components/ui/confirm-dialog';
import * as api from '@/lib/intake/api';
import { EndChatButton } from '../end-chat-button';

mock.module('@/lib/intake/api', () => {
  const actual = require('@/lib/intake/api');
  return { ...actual, endConversation: mock() };
});
const endConvMock = (api as any).endConversation as ReturnType<typeof mock>;

function renderButton(sessionId = 'sess-1') {
  return render(
    <ConfirmDialogProvider>
      <EndChatButton sessionId={sessionId} />
    </ConfirmDialogProvider>,
  );
}

// EndChatButton now uses the accessible ConfirmDialog (not window.confirm): click
// the trigger to open the dialog, then resolve it via its stable action ids.
async function openAndResolve(accept: boolean) {
  fireEvent.click(screen.getByRole('button', { name: /end chat/i }));
  await waitFor(() =>
    expect(document.querySelector('[data-slot="confirm-dialog"]')).toBeTruthy(),
  );
  fireEvent.click(
    document.getElementById(
      accept ? 'confirm-dialog-confirm' : 'confirm-dialog-cancel',
    ) as HTMLElement,
  );
}

beforeEach(() => {
  endConvMock.mockReset();
});

describe('EndChatButton', () => {
  it('calls endConversation with sessionId on click+confirm', async () => {
    endConvMock.mockResolvedValue({ active_modality: null, session: { id: 'sess-1' } as never });
    renderButton();
    await openAndResolve(true);
    await waitFor(() => expect(endConvMock).toHaveBeenCalledWith('sess-1'));
  });

  it('does NOT call endConversation if user cancels confirm', async () => {
    renderButton();
    await openAndResolve(false);
    expect(endConvMock).not.toHaveBeenCalled();
  });

  it('shows error message if endConversation throws', async () => {
    endConvMock.mockRejectedValue(new Error('voice agent did not drain cleanly'));
    renderButton();
    await openAndResolve(true);
    await waitFor(() => {
      const err = document.getElementById('v2-intake-end-chat-error');
      expect(err?.textContent ?? '').toMatch(/drain/i);
    });
  });

  it('disables button while in flight', async () => {
    let resolve!: () => void;
    endConvMock.mockReturnValue(
      new Promise((r) => {
        resolve = () => r({ active_modality: null, session: {} as never });
      }),
    );
    renderButton();
    await openAndResolve(true);
    const btn = document.getElementById('v2-intake-end-chat-button') as HTMLButtonElement;
    await waitFor(() => expect(btn.disabled).toBe(true));
    resolve();
    await waitFor(() => expect(btn.disabled).toBe(false));
  });
});
