// Coverage for the proactive "add a screen?" suggestion banner on the dashboard
// plan tab (Phase 3, Task 3):
//   1. shouldSuggest=true renders the dismissible banner with the reason.
//   2. clicking "Add screening" opens the ScreeningConfigPanel for the SUGGESTED
//      round (the targetRoundId, not necessarily round 1).
//   3. dismissing hides the banner and persists for the session.
//   4. shouldSuggest=false (or a failed fetch) renders no banner.
//
// We spy on the live service modules (restored in afterEach) rather than
// mock.module — bun's mock.module is process-wide and unrestorable (mirrors
// plan-tab.screening.test.tsx).

import { afterEach, beforeEach, describe, expect, spyOn, test } from 'bun:test';
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import type { ComponentType } from 'react';
import { ConfirmDialogProvider } from '@/components/ui/confirm-dialog';
import { ToastProvider } from '@/components/ui/toast';
import type { Requisition, Round } from '@/domain';
import * as screeningModule from '@/services/screening';

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
    name: 'Phone screen',
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

const spies: Array<ReturnType<typeof spyOn>> = [];
afterEach(() => {
  for (const s of spies) s.mockRestore();
  spies.length = 0;
  cleanup();
});
beforeEach(() => {
  spies.length = 0;
  try {
    sessionStorage.clear();
  } catch {}
  // Quiet the per-round config fetch; suggestion is the unit under test.
  spies.push(spyOn(screeningModule, 'getScreening').mockResolvedValue(null));
});

describe('PlanTab — proactive screening suggestion banner', () => {
  test('renders the dismissible banner with the reason when shouldSuggest', async () => {
    spies.push(
      spyOn(screeningModule, 'getScreeningSuggestion').mockResolvedValue({
        shouldSuggest: true,
        reason: '3 candidates were repeatedly weak in System Design.',
        targetRoundId: 'round-1',
      }),
    );
    const { container } = renderPlan(makeRole([makeRound()]));

    await waitFor(() => {
      expect(container.querySelector('#plan-suggestion')).not.toBeNull();
    });
    expect(container.querySelector('#plan-suggestion-reason')?.textContent).toContain(
      'System Design',
    );
    expect(container.querySelector('#plan-suggestion-add')).not.toBeNull();
    expect(container.querySelector('#plan-suggestion-dismiss')).not.toBeNull();
  });

  test('no banner when shouldSuggest is false', async () => {
    spies.push(
      spyOn(screeningModule, 'getScreeningSuggestion').mockResolvedValue({
        shouldSuggest: false,
        reason: '',
        targetRoundId: null,
      }),
    );
    const { container } = renderPlan(makeRole([makeRound()]));

    // Let the effect resolve, then assert nothing rendered.
    await waitFor(() => {
      expect(screeningModule.getScreeningSuggestion).toHaveBeenCalled();
    });
    expect(container.querySelector('#plan-suggestion')).toBeNull();
  });

  test('a failed suggestion fetch shows no banner (silent)', async () => {
    spies.push(
      spyOn(screeningModule, 'getScreeningSuggestion').mockRejectedValue(new Error('cortex down')),
    );
    const { container } = renderPlan(makeRole([makeRound()]));

    await waitFor(() => {
      expect(screeningModule.getScreeningSuggestion).toHaveBeenCalled();
    });
    expect(container.querySelector('#plan-suggestion')).toBeNull();
  });

  test('dismiss hides the banner', async () => {
    spies.push(
      spyOn(screeningModule, 'getScreeningSuggestion').mockResolvedValue({
        shouldSuggest: true,
        reason: 'recurring gap',
        targetRoundId: 'round-1',
      }),
    );
    const { container } = renderPlan(makeRole([makeRound()]));

    await waitFor(() => {
      expect(container.querySelector('#plan-suggestion-dismiss')).not.toBeNull();
    });
    act(() => {
      fireEvent.click(container.querySelector('#plan-suggestion-dismiss') as HTMLElement);
    });
    await waitFor(() => {
      expect(container.querySelector('#plan-suggestion')).toBeNull();
    });
  });

  test('"Add screening" opens the ScreeningConfigPanel for the SUGGESTED round', async () => {
    const getSpy = spyOn(screeningModule, 'getScreening').mockResolvedValue(null);
    spies.push(getSpy);
    spies.push(
      spyOn(screeningModule, 'getScreeningSuggestion').mockResolvedValue({
        shouldSuggest: true,
        reason: 'recurring gap in System Design',
        targetRoundId: 'round-2',
      }),
    );
    const role = makeRole([
      makeRound({ id: 'round-1', round_number: 1 }),
      makeRound({ id: 'round-2', round_number: 2, name: 'Technical' }),
    ]);
    const { container } = renderPlan(role);

    await waitFor(() => {
      expect(container.querySelector('#plan-suggestion-add')).not.toBeNull();
    });
    act(() => {
      fireEvent.click(container.querySelector('#plan-suggestion-add') as HTMLElement);
    });

    // The panel mounts and loads the SUGGESTED round's config (round-2).
    await waitFor(() => {
      expect(container.querySelector('#plan-screening-panel-panel')).not.toBeNull();
    });
    const calledRoundIds = getSpy.mock.calls.map((c) => c[1]);
    expect(calledRoundIds).toContain('round-2');
  });
});
