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
    await waitFor(() => {
      expect(dismissCalls).toEqual(['req-1']);
      expect(container.querySelector('#chip-toggle')).toBeFalsy();
    });
  });

  test('shows the removed pill when deleted in the ATS', async () => {
    syncHandler = async () => ({ ...CLEAN, ats_deleted: true });
    renderChip();
    await waitFor(() => {
      expect(screen.getByText('Removed in Workable')).toBeTruthy();
    });
  });
});
