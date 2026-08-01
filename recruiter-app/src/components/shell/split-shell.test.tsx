import { beforeEach, describe, expect, test } from 'bun:test';
import { fireEvent, render, screen } from '@testing-library/react';
import { useArtifactStore, useSessionStore, useShellStore, useSplitStore } from '@/stores';
import { SplitShell } from './split-shell';

describe('SplitShell', () => {
  beforeEach(() => {
    localStorage.clear();
    useSplitStore.getState().reset();
    useSessionStore.getState().reset();
    useArtifactStore.getState().reset();
    useShellStore.getState().reset();
  });

  test('collapses artifact column when no artifact', () => {
    useShellStore.getState().setActiveTab('intake');
    useSessionStore.getState().startSession('intake', 'mode_choice');
    render(
      <SplitShell id="shell">
        <div>chat body</div>
      </SplitShell>,
    );
    expect(screen.getByText('chat body')).toBeTruthy();
    expect(screen.queryByRole('separator')).toBeNull();
  });

  describe('with artifact open', () => {
    beforeEach(() => {
      useShellStore.getState().setActiveTab('intake');
      useSessionStore.getState().startSession('intake', 'mode_choice');
      useArtifactStore.getState().openArtifact({
        id: 'a1',
        type: 'requisition',
        title: 'X',
        initialData: {
          sub: '',
          published: false,
          rounds: [],
          criteria: [],
          guidelines: [],
        },
      });
      useSessionStore.getState().setArtifactId('intake', 'a1');
    });

    test('renders chat + divider + artifact column', () => {
      render(
        <SplitShell id="shell">
          <div>chat body</div>
        </SplitShell>,
      );
      expect(screen.getByText('chat body')).toBeTruthy();
      expect(screen.getByRole('separator')).toBeTruthy();
    });

    test('divider has separator role with orientation', () => {
      render(
        <SplitShell id="shell">
          <div>chat</div>
        </SplitShell>,
      );
      const divider = screen.getByRole('separator');
      expect(divider.getAttribute('aria-orientation')).toBe('vertical');
    });

    test('ArrowRight on divider increases ratio by 2%', () => {
      render(
        <SplitShell id="shell">
          <div>chat</div>
        </SplitShell>,
      );
      const divider = screen.getByRole('separator');
      divider.focus();
      fireEvent.keyDown(divider, { key: 'ArrowRight' });
      expect(useSplitStore.getState().ratio).toBeCloseTo(0.57, 2);
    });
  });
});
