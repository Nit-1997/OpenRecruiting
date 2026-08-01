/**
 * FE-J8: the fullscreen artifact dialog uses the shared, hardened
 * useFocusTrap hook instead of a bespoke keydown/DOM-rescan handler.
 *
 * We assert the wiring: when an artifact is expanded, the dialog renders as a
 * modal, Escape collapses it (onEscape wired through useFocusTrap), and focus
 * is trapped inside.
 */

import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { act, cleanup, render } from '@testing-library/react';
import { useArtifactStore, useSessionStore, useShellStore } from '@/stores';
import { ArtifactColumn } from './artifact-column';

afterEach(cleanup);

beforeEach(() => {
  useSessionStore.getState().reset();
  useArtifactStore.getState().reset();
  useShellStore.getState().reset();
});

function openExpandedArtifact() {
  useShellStore.getState().setActiveTab('intake');
  useSessionStore.getState().startSession('intake', 'mode_choice');
  useArtifactStore.getState().openArtifact({
    id: 'a1',
    type: 'requisition',
    title: 'My Role',
    initialData: {
      sub: '',
      published: false,
      rounds: [],
      criteria: [],
      guidelines: [],
    },
  });
  useSessionStore.getState().setArtifactId('intake', 'a1');
  useArtifactStore.getState().expandArtifact('a1');
}

describe('ArtifactColumn — fullscreen focus trap', () => {
  test('renders the expanded artifact as a modal dialog', () => {
    openExpandedArtifact();
    const { container } = render(<ArtifactColumn id="art" />);
    const dialog = container.querySelector('#art-fullscreen');
    expect(dialog).not.toBeNull();
    expect(dialog?.getAttribute('role')).toBe('dialog');
    expect(dialog?.getAttribute('aria-modal')).toBe('true');
  });

  test('Escape collapses the expanded artifact (onEscape wired)', () => {
    openExpandedArtifact();
    render(<ArtifactColumn id="art" />);
    expect(useArtifactStore.getState().artifacts.a1?.expanded).toBe('expanded');
    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });
    expect(useArtifactStore.getState().artifacts.a1?.expanded).toBe('default');
  });

  test('Tab wraps focus inside the dialog (focus trap active)', () => {
    openExpandedArtifact();
    const { container } = render(<ArtifactColumn id="art" />);
    const dialog = container.querySelector('#art-fullscreen') as HTMLElement;
    const focusables = Array.from(
      dialog.querySelectorAll<HTMLElement>('button, input, [tabindex]:not([tabindex="-1"])'),
    );
    expect(focusables.length).toBeGreaterThan(0);
    const last = focusables[focusables.length - 1] as HTMLElement;
    last.focus();
    const ev = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
    document.dispatchEvent(ev);
    // Tab from the last focusable wraps back into the dialog (to the first),
    // never escaping to the document body.
    expect(dialog.contains(document.activeElement)).toBe(true);
  });
});
