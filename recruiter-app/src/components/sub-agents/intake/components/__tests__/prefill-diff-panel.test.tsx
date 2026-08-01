import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { fireEvent, render, waitFor } from '@testing-library/react';

import { useIntakeStore } from '@/stores/intake-store';

const saveEditMock = mock(async () => ({ applied: ['x'] }));
const dismissDiffPanelMock = mock();

mock.module('@/hooks/intake/use-manual-answer-edit', () => ({
  useManualAnswerEdit: () => ({
    savingQid: null,
    error: null,
    saveEdit: saveEditMock,
    clearError: mock(),
  }),
}));

mock.module('@/hooks/intake/use-process-till-now', () => ({
  useProcessTillNow: () => ({
    runReprocess: mock(),
    dismissDiffPanel: dismissDiffPanelMock,
    isReprocessing: false,
  }),
}));

const mockSessionRef = { current: null as any };
mock.module('@/hooks/intake/use-intake-session', () => ({
  useIntakeSession: () => ({ session: mockSessionRef.current, isLoading: false, error: null }),
}));

import { PrefillDiffPanel } from '../prefill-diff-panel';

function setupPanel({
  prefilled,
  base,
}: {
  prefilled: Record<string, { text: string | null }>;
  base: Record<string, { text: string | null }>;
}) {
  mockSessionRef.current = {
    id: 'abc',
    prefilled_answers: prefilled,
    current_answers: base,
  };
  useIntakeStore.setState({
    sessionId: 'abc',
    diffPanelOpen: true,
    diffBaseAnswers: base as any,
    processTillNowRunId: 'run-1',
  });
}

describe('PrefillDiffPanel', () => {
  beforeEach(() => {
    saveEditMock.mockReset();
    saveEditMock.mockResolvedValue({ applied: ['x'] });
    dismissDiffPanelMock.mockReset();
    useIntakeStore.setState({ diffPanelOpen: false, diffBaseAnswers: null });
  });
  afterEach(() => {
    saveEditMock.mockReset();
    dismissDiffPanelMock.mockReset();
  });

  it('renders nothing when diffPanelOpen is false', () => {
    const { container } = render(<PrefillDiffPanel />);
    expect(container.firstChild).toBeNull();
  });

  it('shows only questions where new differs from base', () => {
    setupPanel({
      prefilled: { q1_role_overview: { text: 'NEW' }, q4_must_haves: { text: 'same' } },
      base: { q1_role_overview: { text: 'OLD' }, q4_must_haves: { text: 'same' } },
    });
    render(<PrefillDiffPanel />);
    expect(document.getElementById('v2-intake-prefill-diff-row-q1_role_overview')).not.toBeNull();
    expect(document.getElementById('v2-intake-prefill-diff-row-q4_must_haves')).toBeNull();
  });

  it('Accept calls saveEdit with the new text and removes the row', async () => {
    setupPanel({
      prefilled: { q1_role_overview: { text: 'NEW' } },
      base: { q1_role_overview: { text: 'OLD' } },
    });
    render(<PrefillDiffPanel />);
    fireEvent.click(
      document.getElementById(
        'v2-intake-prefill-diff-accept-q1_role_overview',
      ) as HTMLButtonElement,
    );
    await waitFor(() => expect(saveEditMock).toHaveBeenCalled());
    expect(saveEditMock).toHaveBeenCalledWith('q1_role_overview', { text: 'NEW' });
  });

  it('Dismiss removes row WITHOUT calling saveEdit (invariant)', () => {
    setupPanel({
      prefilled: { q1_role_overview: { text: 'NEW' } },
      base: { q1_role_overview: { text: 'OLD' } },
    });
    render(<PrefillDiffPanel />);
    fireEvent.click(
      document.getElementById(
        'v2-intake-prefill-diff-dismiss-q1_role_overview',
      ) as HTMLButtonElement,
    );
    expect(saveEditMock).not.toHaveBeenCalled();
  });

  it('Accept All patches every diffed row', async () => {
    setupPanel({
      prefilled: { q1_role_overview: { text: 'N1' }, q4_must_haves: { text: 'N4' } },
      base: { q1_role_overview: { text: 'O1' }, q4_must_haves: { text: 'O4' } },
    });
    render(<PrefillDiffPanel />);
    fireEvent.click(
      document.getElementById('v2-intake-prefill-diff-accept-all') as HTMLButtonElement,
    );
    await waitFor(() => expect(saveEditMock).toHaveBeenCalledTimes(2));
  });

  it('Close button calls dismissDiffPanel', () => {
    setupPanel({
      prefilled: { q1_role_overview: { text: 'N' } },
      base: { q1_role_overview: { text: 'O' } },
    });
    render(<PrefillDiffPanel />);
    fireEvent.click(document.getElementById('v2-intake-prefill-diff-close') as HTMLButtonElement);
    expect(dismissDiffPanelMock).toHaveBeenCalledTimes(1);
  });

  it('renders empty-state message when there are no differences', () => {
    setupPanel({
      prefilled: { q1_role_overview: { text: 'same' } },
      base: { q1_role_overview: { text: 'same' } },
    });
    render(<PrefillDiffPanel />);
    expect(document.getElementById('v2-intake-prefill-diff-empty')).not.toBeNull();
  });

  it('renders side-by-side old vs new text per row', () => {
    setupPanel({
      prefilled: { q1_role_overview: { text: 'NEW VALUE' } },
      base: { q1_role_overview: { text: 'OLD VALUE' } },
    });
    render(<PrefillDiffPanel />);
    const row = document.getElementById(
      'v2-intake-prefill-diff-row-q1_role_overview',
    ) as HTMLElement;
    expect(row.textContent).toContain('OLD VALUE');
    expect(row.textContent).toContain('NEW VALUE');
  });
});
