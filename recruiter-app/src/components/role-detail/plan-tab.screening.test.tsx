// Coverage for the dashboard plan-tab screening surface (Task 15):
//   1. a `aiScreenable` round (no saved config) renders the "OpenRecruiting can take
//      this round" nudge.
//   2. a round with an ENABLED screening config renders the
//      "OPENRECRUITING TAKES THIS ROUND · NQ" badge (N = configured question count).
//   3. clicking the entry point opens the Task-14 ScreeningConfigPanel for the
//      RIGHT round (panel mounts + loads that round's config).
//
// We spy on the live service modules (restored in afterEach) rather than
// mock.module — bun's mock.module is process-wide and unrestorable (see
// plan-tab.test.tsx for the same pattern).

import { afterEach, beforeEach, describe, expect, spyOn, test } from 'bun:test';
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import type { ComponentType } from 'react';
import { ConfirmDialogProvider } from '@/components/ui/confirm-dialog';
import { ToastProvider } from '@/components/ui/toast';
import type { Requisition, Round } from '@/domain';
import * as screeningModule from '@/services/screening';

// role-detail-page.test.tsx mocks './plan-tab' process-wide with a stub; read
// the GENUINE component from the preload snapshot so this file drives the real
// component regardless of mock order (mirrors plan-tab.test.tsx).
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

function mkConfig(overrides: Partial<screeningModule.ScreeningConfig> = {}) {
  return {
    roundId: 'round-1',
    enabled: false,
    voice: 'Aura · "Luna"',
    followUpStyle: 'Adaptive probes',
    estDurationMinutes: 18,
    validityDays: 7,
    deployScope: 'all_resume_passed',
    questions: [],
    ...overrides,
  } as screeningModule.ScreeningConfig;
}

function mkQuestion(i: number): screeningModule.ScreeningQuestion {
  return {
    id: `q${i}`,
    orderIndex: i,
    title: `Question ${i}`,
    prompt: 'prompt',
    probe: 'probe',
    signal: 'execution',
    dimension: 'ownership',
    durationMinutes: 5,
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
  // Suppress the role-level suggestion fetch; this file covers the per-round surface.
  spies.push(
    spyOn(screeningModule, 'getScreeningSuggestion').mockResolvedValue({
      shouldSuggest: false,
      reason: '',
      targetRoundId: null,
    }),
  );
});

describe('PlanTab — dashboard screening surface', () => {
  test('eligible round (no saved config) renders the nudge, not the badge', async () => {
    spies.push(spyOn(screeningModule, 'getScreening').mockResolvedValue(null));
    const role = makeRole([makeRound({ aiScreenable: true })]);
    const { container } = renderPlan(role);

    await waitFor(() => {
      expect(container.querySelector('#plan-round-round-1-screening-nudge')).not.toBeNull();
    });
    expect(container.querySelector('#plan-round-round-1-screening-badge')).toBeNull();
  });

  test('enabled config renders the "OPENRECRUITING TAKES THIS ROUND · NQ" badge', async () => {
    spies.push(
      spyOn(screeningModule, 'getScreening').mockResolvedValue(
        mkConfig({ enabled: true, questions: [mkQuestion(0), mkQuestion(1), mkQuestion(2)] }),
      ),
    );
    const role = makeRole([makeRound({ aiScreenable: true })]);
    const { container } = renderPlan(role);

    let badge: Element | null = null;
    await waitFor(() => {
      badge = container.querySelector('#plan-round-round-1-screening-badge');
      expect(badge).not.toBeNull();
    });
    expect(badge?.textContent?.toUpperCase()).toContain('OPENRECRUITING TAKES THIS ROUND');
    expect(badge?.textContent).toContain('3Q');
    // Hosted badge wins — the eligibility nudge is suppressed.
    expect(container.querySelector('#plan-round-round-1-screening-nudge')).toBeNull();
  });

  test('recruiter override: a non-eligible, non-enabled round still renders the "Set up screening" entry', async () => {
    spies.push(spyOn(screeningModule, 'getScreening').mockResolvedValue(null));
    // category 'technical' is NOT in the conversational allowlist and there is
    // no saved config — previously the section early-returned null, hiding the
    // ONLY config entry point. It must now render the lighter affordance.
    const role = makeRole([
      makeRound({ category: 'technical', aiScreenable: false }),
    ]);
    const { container } = renderPlan(role);

    let section: Element | null = null;
    await waitFor(() => {
      section = container.querySelector('#plan-round-round-1-screening');
      expect(section).not.toBeNull();
    });
    // The "Set up screening" configure button is reachable.
    const configure = container.querySelector('#plan-round-round-1-screening-configure');
    expect(configure).not.toBeNull();
    expect(configure?.textContent).toContain('Set up screening');
    // Not auto-recommended: no header nudge / badge for a non-conversational round.
    expect(container.querySelector('#plan-round-round-1-screening-nudge')).toBeNull();
    expect(container.querySelector('#plan-round-round-1-screening-badge')).toBeNull();
  });

  test('clicking the nudge opens the ScreeningConfigPanel for that round', async () => {
    const getSpy = spyOn(screeningModule, 'getScreening').mockResolvedValue(null);
    spies.push(getSpy);
    const role = makeRole([makeRound({ id: 'round-1', aiScreenable: true })]);
    const { container } = renderPlan(role);

    await waitFor(() => {
      expect(container.querySelector('#plan-round-round-1-screening-nudge')).not.toBeNull();
    });

    act(() => {
      fireEvent.click(container.querySelector('#plan-round-round-1-screening-nudge') as HTMLElement);
    });

    // The Task-14 panel mounts with the plan-derived id and loads the round's
    // config (the second getScreening call is the panel's own initial load).
    await waitFor(() => {
      expect(container.querySelector('#plan-screening-panel-panel')).not.toBeNull();
    });
    expect(container.querySelector('#plan-screening-panel-title')?.textContent).toContain(
      'Screening Agent',
    );
    // The panel was asked for THIS round's config.
    const calledRoundIds = getSpy.mock.calls.map((c) => c[1]);
    expect(calledRoundIds).toContain('round-1');
  });
});
