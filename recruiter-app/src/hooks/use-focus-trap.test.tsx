import { afterEach, describe, expect, test } from 'bun:test';
import { cleanup, render } from '@testing-library/react';
import { useRef } from 'react';
import { useFocusTrap } from './use-focus-trap';

function Trap({ active, onEscape }: { active: boolean; onEscape?: () => void }) {
  const ref = useRef<HTMLDivElement | null>(null);
  useFocusTrap(ref, active, onEscape);
  return (
    <div ref={ref} data-testid="trap">
      <button type="button" id="first">
        first
      </button>
      <button type="button" id="mid">
        mid
      </button>
      <button type="button" id="last">
        last
      </button>
    </div>
  );
}

afterEach(() => {
  cleanup();
});

describe('useFocusTrap', () => {
  test('focuses first focusable when active and nothing has focus', () => {
    render(<Trap active />);
    expect(document.activeElement?.id).toBe('first');
  });

  test('Escape key calls onEscape', () => {
    let escaped = 0;
    render(
      <Trap
        active
        onEscape={() => {
          escaped += 1;
        }}
      />,
    );
    const ev = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true });
    document.dispatchEvent(ev);
    expect(escaped).toBe(1);
  });

  test('Tab from the last focusable wraps to the first', () => {
    render(<Trap active />);
    const last = document.getElementById('last') as HTMLButtonElement;
    last.focus();
    expect(document.activeElement).toBe(last);
    const ev = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
    document.dispatchEvent(ev);
    expect(document.activeElement?.id).toBe('first');
  });

  test('Shift-Tab from the first focusable wraps to the last', () => {
    render(<Trap active />);
    const first = document.getElementById('first') as HTMLButtonElement;
    first.focus();
    const ev = new KeyboardEvent('keydown', {
      key: 'Tab',
      shiftKey: true,
      bubbles: true,
      cancelable: true,
    });
    document.dispatchEvent(ev);
    expect(document.activeElement?.id).toBe('last');
  });

  test('does not trap focus when inactive', () => {
    render(<Trap active={false} />);
    // No element should be auto-focused.
    expect(document.activeElement?.id).not.toBe('first');
  });

  test('skips a display:none trailing focusable when wrapping forward', () => {
    render(
      <div data-testid="trap">
        <TrapHidden />
      </div>,
    );
    const visibleLast = document.getElementById('visible-last') as HTMLButtonElement;
    visibleLast.focus();
    const ev = new KeyboardEvent('keydown', {
      key: 'Tab',
      bubbles: true,
      cancelable: true,
    });
    document.dispatchEvent(ev);
    // Tab from the last VISIBLE focusable wraps to first; the hidden trailing
    // button must not be considered the "last" focusable.
    expect(document.activeElement?.id).toBe('visible-first');
  });

  test('does not auto-focus a hidden first element on open', () => {
    render(
      <div data-testid="trap">
        <HiddenFirst />
      </div>,
    );
    // The first DOM-order focusable is hidden; focus must land on the first
    // *visible* focusable instead.
    expect(document.activeElement?.id).toBe('real-first');
  });
});

function TrapHidden() {
  const ref = useRef<HTMLDivElement | null>(null);
  useFocusTrap(ref, true);
  return (
    <div ref={ref}>
      <button type="button" id="visible-first">
        first
      </button>
      <button type="button" id="visible-last">
        last
      </button>
      <button type="button" id="hidden-trailing" style={{ display: 'none' }}>
        hidden
      </button>
    </div>
  );
}

function HiddenFirst() {
  const ref = useRef<HTMLDivElement | null>(null);
  useFocusTrap(ref, true);
  return (
    <div ref={ref}>
      <button type="button" id="hidden-first" style={{ display: 'none' }}>
        hidden
      </button>
      <button type="button" id="real-first">
        real first
      </button>
    </div>
  );
}
