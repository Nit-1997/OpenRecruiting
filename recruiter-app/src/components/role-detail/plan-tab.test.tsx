// Tests for the FE-J4 correctness fixes in PlanTab:
//   1. changing round TYPE then CATEGORY persists the LATEST category
//      (no stale-closure regression from the old setTimeout(save,0)).
//   2. a failing updateRound surfaces an error toast (not a silent .catch).
//   3. a destructive action (delete round) goes through ConfirmDialog,
//      NOT window.confirm.
//
// We spy on the live `@/services/requisitions` exports (restored in afterEach)
// rather than mock.module — bun's mock.module is process-wide and unrestorable.

import { afterEach, beforeEach, describe, expect, spyOn, test } from 'bun:test';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ComponentType } from 'react';
import { ConfirmDialogProvider } from '@/components/ui/confirm-dialog';
import { ToastProvider } from '@/components/ui/toast';
import type { Requisition, Round } from '@/domain';
import * as requisitionsModule from '@/services/requisitions';
import * as screeningModule from '@/services/screening';

// role-detail-page.test.tsx mocks './plan-tab' process-wide with a stub. Read
// the GENUINE component from the preload snapshot (test-setup.ts) so this file
// drives the real inline editors/confirm dialog regardless of mock order.
const { PlanTab } =
  (
    globalThis as {
      __REAL_PLAN_TAB__?: { PlanTab: ComponentType<{ id: string; role: Requisition }> };
    }
  ).__REAL_PLAN_TAB__ ?? (await import('./plan-tab'));

function makeRound(overrides: Partial<Round> = {}): Round {
  return {
    id: 'round-1',
    requisition_id: 'role-1',
    round_number: 1,
    name: 'Screening call',
    category: 'screening',
    duration_minutes: 30,
    skills: [],
    guidelines: [],
    feedback_questions: [],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

function makeRole(rounds: Round[]): Requisition {
  return {
    id: 'role-1',
    organization_id: 'org-1',
    role_title: 'Engineer',
    role_location: 'Remote',
    department: 'Eng',
    created_by: 'u1',
    created_by_name: 'Jane',
    experience_min_years: 0,
    experience_max_years: null,
    status: 'planned',
    intake_notes: '',
    job_description: '',
    must_have_skills: [],
    good_to_have_skills: [],
    rounds,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  };
}

function renderPlan(role: Requisition) {
  return render(
    <ToastProvider>
      <ConfirmDialogProvider>
        <PlanTab id="plan" role={role} />
      </ConfirmDialogProvider>
    </ToastProvider>,
  );
}

// Enter edit mode so the inline editors render.
function enterEditMode() {
  act(() => {
    fireEvent.click(document.getElementById('plan-edit-toggle') as HTMLElement);
  });
}

let updateSpy: ReturnType<typeof spyOn> | null = null;
let deleteSpy: ReturnType<typeof spyOn> | null = null;
let screeningSpy: ReturnType<typeof spyOn> | null = null;
let suggestionSpy: ReturnType<typeof spyOn> | null = null;

// PlanTab now light-fetches each round's saved screening config + a role-level
// "add a screen?" suggestion on mount. Stub both here so these
// (screening-agnostic) tests don't fire real HTTP.
beforeEach(() => {
  screeningSpy = spyOn(screeningModule, 'getScreening').mockResolvedValue(null);
  suggestionSpy = spyOn(screeningModule, 'getScreeningSuggestion').mockResolvedValue({
    shouldSuggest: false,
    reason: '',
    targetRoundId: null,
  });
});

afterEach(() => {
  updateSpy?.mockRestore();
  updateSpy = null;
  deleteSpy?.mockRestore();
  deleteSpy = null;
  screeningSpy?.mockRestore();
  screeningSpy = null;
  suggestionSpy?.mockRestore();
  suggestionSpy = null;
  cleanup();
});

describe('PlanTab — category/type race (no stale-closure save)', () => {
  beforeEach(() => {
    updateSpy = spyOn(requisitionsModule, 'updateRound').mockResolvedValue(makeRound() as never);
  });

  test('changing the type select persists the CURRENT name + the NEW category', async () => {
    const role = makeRole([makeRound({ name: 'Screening call', category: 'screening' })]);
    renderPlan(role);
    enterEditMode();

    const select = document.getElementById('plan-round-round-1-type') as HTMLSelectElement;
    await act(async () => {
      fireEvent.change(select, { target: { value: 'technical' } });
    });

    expect(updateSpy).toHaveBeenCalledTimes(1);
    // The category persisted must be the NEW one ('technical'), with the
    // existing name carried along — proving no stale read.
    const [roundId, patch] = (updateSpy as ReturnType<typeof spyOn>).mock.calls[0] as [
      string,
      { name?: string; category?: string },
    ];
    expect(roundId).toBe('round-1');
    expect(patch.category).toBe('technical');
    expect(patch.name).toBe('Screening call');
  });
});

describe('PlanTab — failing save surfaces an error (no silent swallow)', () => {
  test('a rejected updateRound shows an error toast', async () => {
    updateSpy = spyOn(requisitionsModule, 'updateRound').mockRejectedValue(
      new Error('server exploded'),
    );
    const role = makeRole([makeRound()]);
    renderPlan(role);
    enterEditMode();

    const select = document.getElementById('plan-round-round-1-type') as HTMLSelectElement;
    await act(async () => {
      fireEvent.change(select, { target: { value: 'technical' } });
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(screen.getByText(/Could not save round/i)).toBeTruthy();
    });
  });
});

describe('PlanTab — destructive actions go through ConfirmDialog', () => {
  test('deleting a round opens the ConfirmDialog (not window.confirm)', async () => {
    deleteSpy = spyOn(requisitionsModule, 'deleteRound').mockResolvedValue(undefined as never);
    // Two rounds so the delete button isn't disabled (total > 1).
    const role = makeRole([
      makeRound({ id: 'round-1', round_number: 1 }),
      makeRound({ id: 'round-2', round_number: 2, name: 'Tech' }),
    ]);
    renderPlan(role);
    enterEditMode();

    const deleteBtn = document.querySelector(
      '#plan-round-round-1 button[aria-label="Delete round"]',
    ) as HTMLElement;
    await act(async () => {
      fireEvent.click(deleteBtn);
    });

    // A styled, accessible confirm dialog appears — deleteRound NOT called yet.
    const dialog = document.querySelector('[data-slot="confirm-dialog"]');
    expect(dialog).toBeTruthy();
    expect(deleteSpy).not.toHaveBeenCalled();

    // Confirming triggers the delete.
    await act(async () => {
      fireEvent.click(document.getElementById('confirm-dialog-confirm') as HTMLElement);
    });
    expect(deleteSpy).toHaveBeenCalledWith('round-1');
  });

  test('cancelling the confirm does NOT delete', async () => {
    deleteSpy = spyOn(requisitionsModule, 'deleteRound').mockResolvedValue(undefined as never);
    const role = makeRole([
      makeRound({ id: 'round-1', round_number: 1 }),
      makeRound({ id: 'round-2', round_number: 2, name: 'Tech' }),
    ]);
    renderPlan(role);
    enterEditMode();

    const deleteBtn = document.querySelector(
      '#plan-round-round-1 button[aria-label="Delete round"]',
    ) as HTMLElement;
    await act(async () => {
      fireEvent.click(deleteBtn);
    });
    await act(async () => {
      fireEvent.click(document.getElementById('confirm-dialog-cancel') as HTMLElement);
    });

    expect(deleteSpy).not.toHaveBeenCalled();
    expect(document.querySelector('[data-slot="confirm-dialog"]')).toBeNull();
  });
});
