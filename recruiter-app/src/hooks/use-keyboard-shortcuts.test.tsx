import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { cleanup, render } from '@testing-library/react';
import { useKeyboardShortcuts } from './use-keyboard-shortcuts';

function Harness() {
  useKeyboardShortcuts();
  return <input id="app-shell-composer-input" data-testid="composer" />;
}

function QnaHarness() {
  useKeyboardShortcuts();
  return (
    <div>
      <input id="app-shell-qna-chat-composer-input" data-testid="qna" />
      <input id="app-shell-composer-input" data-testid="composer" />
    </div>
  );
}

function dispatchMetaK(key = 'k'): void {
  const ev = new KeyboardEvent('keydown', { key, metaKey: true, bubbles: true });
  document.dispatchEvent(ev);
}

function dispatchCtrlK(key = 'k'): void {
  const ev = new KeyboardEvent('keydown', { key, ctrlKey: true, bubbles: true });
  document.dispatchEvent(ev);
}

beforeEach(() => {
  document.body.innerHTML = '';
});

afterEach(() => {
  cleanup();
});

describe('useKeyboardShortcuts', () => {
  test('⌘K focuses the composer input when qna is not mounted', () => {
    const { getByTestId } = render(<Harness />);
    const composer = getByTestId('composer') as HTMLInputElement;
    expect(document.activeElement).not.toBe(composer);
    dispatchMetaK();
    expect(document.activeElement).toBe(composer);
  });

  test('Ctrl+K (non-Mac) also focuses the composer input', () => {
    const { getByTestId } = render(<Harness />);
    const composer = getByTestId('composer') as HTMLInputElement;
    dispatchCtrlK();
    expect(document.activeElement).toBe(composer);
  });

  test('⌘K prefers the qna composer when one is mounted', () => {
    const { getByTestId } = render(<QnaHarness />);
    const qna = getByTestId('qna') as HTMLInputElement;
    const composer = getByTestId('composer') as HTMLInputElement;
    dispatchMetaK();
    expect(document.activeElement).toBe(qna);
    expect(document.activeElement).not.toBe(composer);
  });

  test('uppercase K also triggers the chord', () => {
    const { getByTestId } = render(<Harness />);
    const composer = getByTestId('composer') as HTMLInputElement;
    dispatchMetaK('K');
    expect(document.activeElement).toBe(composer);
  });

  test('keyboard events without meta/ctrl are ignored', () => {
    const { getByTestId } = render(<Harness />);
    const composer = getByTestId('composer') as HTMLInputElement;
    const ev = new KeyboardEvent('keydown', { key: 'k', bubbles: true });
    document.dispatchEvent(ev);
    expect(document.activeElement).not.toBe(composer);
  });
});
