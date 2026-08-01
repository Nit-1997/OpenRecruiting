import { afterEach, describe, expect, test } from 'bun:test';
import { cleanup, fireEvent, render } from '@testing-library/react';
import { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from './dialog';

afterEach(cleanup);

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<button id="dlg-trigger" type="button">Open</button>} />
      <DialogContent>
        <DialogTitle>Settings</DialogTitle>
        <DialogDescription>Edit your settings.</DialogDescription>
        <button id="dlg-inside" type="button">
          Inside
        </button>
      </DialogContent>
    </Dialog>
  );
}

function popup(): HTMLElement | null {
  return document.querySelector('[data-slot="dialog-content"]');
}

describe('Dialog (a11y)', () => {
  test('content carries role="dialog" and aria-modal="true"', () => {
    render(<Harness />);
    fireEvent.click(document.getElementById('dlg-trigger') as HTMLElement);
    const el = popup();
    expect(el).toBeTruthy();
    expect(el?.getAttribute('role')).toBe('dialog');
    expect(el?.getAttribute('aria-modal')).toBe('true');
  });

  test('is labelled by its title (aria-labelledby points at DialogTitle)', () => {
    render(<Harness />);
    fireEvent.click(document.getElementById('dlg-trigger') as HTMLElement);
    const el = popup();
    const labelledBy = el?.getAttribute('aria-labelledby');
    expect(labelledBy).toBeTruthy();
    const title = labelledBy ? document.getElementById(labelledBy) : null;
    expect(title?.textContent).toBe('Settings');
  });

  test('Escape closes the dialog', () => {
    render(<Harness />);
    fireEvent.click(document.getElementById('dlg-trigger') as HTMLElement);
    expect(popup()).toBeTruthy();
    fireEvent.keyDown(popup() as HTMLElement, { key: 'Escape' });
    expect(popup()).toBeNull();
  });

  test('focus returns to the trigger when the dialog closes', () => {
    render(<Harness />);
    const trigger = document.getElementById('dlg-trigger') as HTMLElement;
    trigger.focus();
    fireEvent.click(trigger);
    expect(popup()).toBeTruthy();
    fireEvent.keyDown(popup() as HTMLElement, { key: 'Escape' });
    expect(popup()).toBeNull();
    expect(document.activeElement?.id).toBe('dlg-trigger');
  });
});
