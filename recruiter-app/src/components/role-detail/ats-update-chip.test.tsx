import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ToastProvider } from '@/components/ui/toast';
import type { AtsRequisitionSync } from '@/services/integrations-ats';

// Mock one layer deeper (the service module) with ...actual spread — same
// order-immunity pattern as ats-card.test.tsx (see CLAUDE.md bun rules).
const actual = await import('@/services/integrations-ats');

let syncHandler: () => Promise<AtsRequisitionSync>;
let applyCalls: string[] = [];
let dismissCalls: string[] = [];

mock.module('@/services/integrations-ats', () => ({
  ...actual,
  getRequisitionAtsSync: () => syncHandler(),
  applyAtsUpdate: async (id: string) => {
    applyCalls.push(id);
  },
  dismissAtsUpdate: async (id: string) => {
    dismissCalls.push(id);
  },
}));

const { AtsUpdateChip } = await import('./ats-update-chip');

const DIRTY: AtsRequisitionSync = {
  linked: true,
  provider: 'workable',
  ats_status: 'OPEN',
  ats_dirty: true,
  ats_deleted: false,
  pending_changes: { role_title: 'SWE II' },
};

const CLEAN: AtsRequisitionSync = { ...DIRTY, ats_dirty: false, pending_changes: null };

function renderChip(onApplied?: () => void) {
  return render(
    <ToastProvider>
      <AtsUpdateChip id="chip" requisitionId="req-1" onApplied={onApplied} />
    </ToastProvider>,
  );
}

// Poll a condition under `act` instead of `waitFor`.
//
// `waitFor` does not reliably resolve here on Linux — which is what CI runs, so
// this test failed every run there while passing on macOS. Instrumented: its
// callback SUCCEEDS (dismiss recorded, chip gone) on the second poll and the
// promise still never settles, so the test burned its full 5s timeout. Only two
// polls happened in those 5 seconds, against a 50ms interval — the retry path
// stops being driven once the DOM stops mutating, and the success never
// propagates out. The component is fine; the wait primitive is not.
//
// This drives React's own queue instead: each turn flushes effects and pending
// promises inside `act`, so the dismiss -> refresh -> setSync chain settles.
// Condition-based rather than a fixed sleep, so a slow CI runner cannot flake it
// and the failure message names what never came true.
async function actUntil(predicate: () => boolean, label: string): Promise<void> {
  for (let i = 0; i < 100; i += 1) {
    if (predicate()) return;
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
  }
  throw new Error(`actUntil: timed out waiting for ${label}`);
}

describe('AtsUpdateChip', () => {
  beforeEach(() => {
    syncHandler = async () => DIRTY;
    applyCalls = [];
    dismissCalls = [];
  });

  afterEach(() => {
    cleanup();
  });

  test('renders the review chip when dirty and expands to pending changes', async () => {
    renderChip();
    await waitFor(() => {
      expect(screen.getByText('Updated in Workable — review')).toBeTruthy();
    });
    fireEvent.click(document.getElementById('chip-toggle') as HTMLElement);
    expect(screen.getByText('SWE II')).toBeTruthy();
    expect(screen.getByText('Title')).toBeTruthy();
  });

  test('renders nothing when clean', async () => {
    syncHandler = async () => CLEAN;
    const { container } = renderChip();
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.querySelector('#chip')).toBeFalsy();
  });

  test('apply calls the service, refreshes, and notifies the parent', async () => {
    let applied = false;
    let calls = 0;
    syncHandler = async () => {
      calls += 1;
      return calls > 1 ? CLEAN : DIRTY;
    };
    renderChip(() => {
      applied = true;
    });
    await waitFor(() => {
      expect(document.getElementById('chip-toggle')).toBeTruthy();
    });
    fireEvent.click(document.getElementById('chip-toggle') as HTMLElement);
    fireEvent.click(document.getElementById('chip-apply') as HTMLElement);
    await waitFor(() => {
      expect(applyCalls).toEqual(['req-1']);
      expect(applied).toBe(true);
    });
  });

  test('dismiss calls the service and hides after refresh', async () => {
    let calls = 0;
    syncHandler = async () => {
      calls += 1;
      return calls > 1 ? CLEAN : DIRTY;
    };
    const { container } = renderChip();
    await waitFor(() => {
      expect(document.getElementById('chip-toggle')).toBeTruthy();
    });
    fireEvent.click(document.getElementById('chip-toggle') as HTMLElement);
    fireEvent.click(document.getElementById('chip-dismiss') as HTMLElement);
    await actUntil(
      () => dismissCalls.length > 0 && !container.querySelector('#chip-toggle'),
      'the dismiss call to land and the chip to disappear',
    );
    expect(dismissCalls).toEqual(['req-1']);
    expect(container.querySelector('#chip-toggle')).toBeFalsy();
  });

  test('shows the removed pill when deleted in the ATS', async () => {
    syncHandler = async () => ({ ...CLEAN, ats_deleted: true });
    renderChip();
    await waitFor(() => {
      expect(screen.getByText('Removed in Workable')).toBeTruthy();
    });
  });
});
