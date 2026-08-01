import { afterEach, describe, expect, test } from 'bun:test';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ConfirmDialogProvider, useConfirm } from './confirm-dialog';

afterEach(cleanup);

function Harness({ onResult }: { onResult: (v: boolean) => void }) {
  const confirm = useConfirm();
  return (
    <button
      id="ask"
      type="button"
      onClick={async () => {
        const ok = await confirm({
          title: 'Delete role?',
          body: 'This cannot be undone.',
          confirmLabel: 'Delete',
          danger: true,
        });
        onResult(ok);
      }}
    >
      ask
    </button>
  );
}

function renderWithProvider(onResult: (v: boolean) => void) {
  return render(
    <ConfirmDialogProvider>
      <Harness onResult={onResult} />
    </ConfirmDialogProvider>,
  );
}

function dialog(): HTMLElement | null {
  return document.querySelector('[data-slot="confirm-dialog"]');
}

describe('ConfirmDialog', () => {
  test('opens an accessible dialog when confirm() is called', () => {
    renderWithProvider(() => {});
    act(() => {
      fireEvent.click(document.getElementById('ask') as HTMLElement);
    });
    const el = dialog();
    expect(el).toBeTruthy();
    expect(el?.getAttribute('role')).toBe('dialog');
    expect(el?.getAttribute('aria-modal')).toBe('true');
    expect(screen.getByText('Delete role?')).toBeTruthy();
  });

  test('resolves true when the confirm button is pressed', async () => {
    let resolved: boolean | undefined;
    renderWithProvider((v) => {
      resolved = v;
    });
    act(() => {
      fireEvent.click(document.getElementById('ask') as HTMLElement);
    });
    await act(async () => {
      fireEvent.click(
        document.getElementById('confirm-dialog-confirm') as HTMLElement,
      );
    });
    expect(resolved).toBe(true);
    expect(dialog()).toBeNull();
  });

  test('resolves false when the cancel button is pressed', async () => {
    let resolved: boolean | undefined;
    renderWithProvider((v) => {
      resolved = v;
    });
    act(() => {
      fireEvent.click(document.getElementById('ask') as HTMLElement);
    });
    await act(async () => {
      fireEvent.click(
        document.getElementById('confirm-dialog-cancel') as HTMLElement,
      );
    });
    expect(resolved).toBe(false);
    expect(dialog()).toBeNull();
  });

  test('resolves false when Escape is pressed', async () => {
    let resolved: boolean | undefined;
    renderWithProvider((v) => {
      resolved = v;
    });
    act(() => {
      fireEvent.click(document.getElementById('ask') as HTMLElement);
    });
    await act(async () => {
      fireEvent.keyDown(dialog() as HTMLElement, { key: 'Escape' });
    });
    expect(resolved).toBe(false);
    expect(dialog()).toBeNull();
  });
});
