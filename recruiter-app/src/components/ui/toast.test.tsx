import { afterEach, describe, expect, test } from 'bun:test';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ToastProvider, useToast } from './toast';

afterEach(cleanup);

function Emitter() {
  const { showToast } = useToast();
  return (
    <div>
      <button
        id="emit-info"
        type="button"
        onClick={() => showToast('Saved', 'info')}
      >
        info
      </button>
      <button
        id="emit-error"
        type="button"
        onClick={() => showToast('Boom', 'error')}
      >
        error
      </button>
    </div>
  );
}

function renderWithProvider() {
  return render(
    <ToastProvider>
      <Emitter />
    </ToastProvider>,
  );
}

describe('Toast (a11y)', () => {
  test('container is a live region (role=status, aria-live=polite)', () => {
    renderWithProvider();
    const region = screen.getByRole('status');
    expect(region.getAttribute('aria-live')).toBe('polite');
  });

  test('error toasts are announced assertively', () => {
    renderWithProvider();
    act(() => {
      fireEvent.click(document.getElementById('emit-error') as HTMLElement);
    });
    const announced = screen.getByText('Boom');
    const liveAncestor = announced.closest('[aria-live]');
    expect(liveAncestor?.getAttribute('aria-live')).toBe('assertive');
  });

  test('generated toast ids are unique across rapid emits', () => {
    renderWithProvider();
    const seen = new Set<string>();
    act(() => {
      for (let i = 0; i < 25; i += 1) {
        fireEvent.click(document.getElementById('emit-info') as HTMLElement);
      }
    });
    const items = document.querySelectorAll('[data-slot="toast-item"]');
    expect(items.length).toBeGreaterThan(0);
    for (const item of items) {
      const id = item.getAttribute('data-toast-id');
      expect(id).toBeTruthy();
      expect(seen.has(id as string)).toBe(false);
      seen.add(id as string);
    }
  });
});
