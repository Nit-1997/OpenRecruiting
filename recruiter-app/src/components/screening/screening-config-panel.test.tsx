// FE coverage for the recruiter Screening Agent config panel.
//
// We spy on the live `@/services/screening` exports (restored in afterEach)
// rather than mock.module — bun's mock.module is process-wide and unrestorable
// (see plan-tab.test.tsx for the same pattern). The panel is wrapped in
// ToastProvider because it surfaces errors via the shared toast.

import { afterEach, beforeEach, describe, expect, spyOn, test } from 'bun:test';
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import { ToastProvider } from '@/components/ui/toast';
import type { ScreeningConfig, ScreeningQuestion } from '@/services/screening';
import * as screeningModule from '@/services/screening';
import type { Round } from '@/types';
import { ScreeningConfigPanel } from './screening-config-panel';

function defined<T>(x: T | null | undefined): T {
  if (x === null || x === undefined) throw new Error('expected defined');
  return x;
}

function mkQuestion(overrides: Partial<ScreeningQuestion> = {}): ScreeningQuestion {
  return {
    id: 'q1',
    orderIndex: 0,
    title: 'Metric ownership',
    prompt: 'Walk me through a metric you owned end to end.',
    probe: 'What did you do when it dipped?',
    signal: 'execution',
    dimension: 'ownership',
    durationMinutes: 5,
    ...overrides,
  };
}

function mkConfig(overrides: Partial<ScreeningConfig> = {}): ScreeningConfig {
  return {
    roundId: 'round-1',
    enabled: false,
    voice: 'Aura · "Luna"',
    followUpStyle: 'Adaptive probes',
    estDurationMinutes: 18,
    validityDays: 7,
    deployScope: 'all_resume_passed',
    questions: [mkQuestion()],
    ...overrides,
  };
}

function mkRound(overrides: Partial<Round> = {}): Round {
  return {
    id: 'round-1',
    requisitionId: 'req-1',
    roundNumber: 1,
    name: 'Recruiter Screen',
    category: 'screening',
    durationMinutes: 30,
    description: '',
    skills: [],
    guidelines: [],
    feedbackQuestions: [],
    ...overrides,
  };
}

function renderPanel(round: Round = mkRound(), onClose = () => {}) {
  return render(
    <ToastProvider>
      <ScreeningConfigPanel
        id="sp"
        requisitionId="req-1"
        roundId="round-1"
        round={round}
        onClose={onClose}
      />
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
  // The panel mounts <PersonaRubric>, which loads its persona on mount. Stub it
  // to an empty persona so these tests don't hit the network for it.
  spies.push(
    spyOn(screeningModule, 'getPersona').mockResolvedValue({
      personaId: null,
      composedText: '',
      dimensions: [],
    }),
  );
  // The rubric also mounts <PersonaPicker>, which loads the saved-persona library
  // on mount. Stub it so these tests don't hit the network for it.
  spies.push(spyOn(screeningModule, 'listPersonas').mockResolvedValue([]));
});

describe('ScreeningConfigPanel', () => {
  test('renders the loaded config: header, summary bar, question cards', async () => {
    spies.push(spyOn(screeningModule, 'getScreening').mockResolvedValue(mkConfig()));

    const { container } = renderPanel();

    await waitFor(() => {
      expect(container.querySelector('#sp-q-0')).not.toBeNull();
    });

    expect(defined(container.querySelector('#sp-title')).textContent).toContain('Screening Agent');
    expect(defined(container.querySelector('#sp-subtitle')).textContent).toContain(
      'Recruiter Screen',
    );
    // Summary bar cells.
    expect(container.querySelector('#sp-summary-voice')).not.toBeNull();
    expect(container.querySelector('#sp-summary-duration')).not.toBeNull();
    expect(container.querySelector('#sp-summary-followup')).not.toBeNull();
    expect(container.querySelector('#sp-summary-deploy')).not.toBeNull();
    // The single question card from getScreening.
    expect(defined(container.querySelector('#sp-q-0')).textContent?.toUpperCase()).toContain(
      'METRIC OWNERSHIP',
    );
  });

  test('Generate questions calls generateScreening and renders returned cards', async () => {
    spies.push(spyOn(screeningModule, 'getScreening').mockResolvedValue(null));
    const generated = mkConfig({
      questions: [
        mkQuestion({ id: undefined, title: 'Pricing instinct', orderIndex: 0 }),
        mkQuestion({ id: undefined, title: 'Conflict story', orderIndex: 1 }),
      ],
    });
    const genSpy = spyOn(screeningModule, 'generateScreening').mockResolvedValue(generated);
    spies.push(genSpy);

    const { container } = renderPanel();

    // Empty state first (no saved config).
    await waitFor(() => {
      expect(container.querySelector('#sp-generate')).not.toBeNull();
    });

    act(() => {
      fireEvent.click(defined(container.querySelector('#sp-generate')));
    });

    await waitFor(() => {
      expect(container.querySelector('#sp-q-1')).not.toBeNull();
    });
    expect(genSpy).toHaveBeenCalledTimes(1);
    expect(defined(container.querySelector('#sp-q-0')).textContent?.toUpperCase()).toContain(
      'PRICING INSTINCT',
    );
  });

  test('editing a question then save calls saveScreening with the edited question', async () => {
    spies.push(spyOn(screeningModule, 'getScreening').mockResolvedValue(mkConfig()));
    const saveSpy = spyOn(screeningModule, 'saveScreening').mockImplementation(
      async (_req, _round, cfg) => cfg,
    );
    spies.push(saveSpy);

    const { container } = renderPanel();

    await waitFor(() => {
      expect(container.querySelector('#sp-q-0')).not.toBeNull();
    });

    // Enter edit mode on the first question + change its title.
    act(() => {
      fireEvent.click(defined(container.querySelector('#sp-q-0-edit')));
    });
    const titleInput = defined(container.querySelector('#sp-q-0-edit-title')) as HTMLInputElement;
    act(() => {
      fireEvent.change(titleInput, { target: { value: 'Edited title' } });
    });

    act(() => {
      fireEvent.click(defined(container.querySelector('#sp-save')));
    });

    await waitFor(() => {
      expect(saveSpy).toHaveBeenCalledTimes(1);
    });
    const savedConfig = saveSpy.mock.calls[0]?.[2] as ScreeningConfig;
    expect(savedConfig.questions[0]?.title).toBe('Edited title');
  });

  test('Attach persists the config via saveScreening with enabled:true (not attachScreening)', async () => {
    // Regression for "Cannot read properties of null (reading 'round_id')":
    // when the recruiter generated questions but never clicked Save, there is no
    // round_screening_configs row. attachScreening flipped a flag on a missing
    // row → backend returned null → configFromWire(null) threw a TypeError.
    // Attach now PUTs the full config (upsert), guaranteeing the row exists.
    spies.push(spyOn(screeningModule, 'getScreening').mockResolvedValue(mkConfig()));
    const saveSpy = spyOn(screeningModule, 'saveScreening').mockImplementation(
      async (_r, _n, c) => c,
    );
    spies.push(saveSpy);
    const attachSpy = spyOn(screeningModule, 'attachScreening').mockResolvedValue(
      mkConfig({ enabled: true }),
    );
    spies.push(attachSpy);

    const { container } = renderPanel();

    await waitFor(() => {
      expect(container.querySelector('#sp-attach')).not.toBeNull();
    });

    act(() => {
      fireEvent.click(defined(container.querySelector('#sp-attach')));
    });

    await waitFor(() => {
      expect(saveSpy).toHaveBeenCalledTimes(1);
    });
    // The panel persists via saveScreening (upsert), NOT the flip-only attach.
    expect(attachSpy).not.toHaveBeenCalled();
    expect(saveSpy.mock.calls[0]?.[0]).toBe('req-1');
    expect(saveSpy.mock.calls[0]?.[1]).toBe('round-1');
    const savedCfg = saveSpy.mock.calls[0]?.[2] as ScreeningConfig;
    expect(savedCfg.enabled).toBe(true);
    expect(savedCfg.questions[0]?.title).toBe('Metric ownership');
  });

  test('Attach when already enabled persists enabled:false (detach via save)', async () => {
    spies.push(
      spyOn(screeningModule, 'getScreening').mockResolvedValue(mkConfig({ enabled: true })),
    );
    const saveSpy = spyOn(screeningModule, 'saveScreening').mockImplementation(
      async (_r, _n, c) => c,
    );
    spies.push(saveSpy);
    const detachSpy = spyOn(screeningModule, 'detachScreening').mockResolvedValue(
      mkConfig({ enabled: false }),
    );
    spies.push(detachSpy);

    const { container } = renderPanel(mkRound({ screeningAgentEnabled: true }));

    await waitFor(() => {
      expect(container.querySelector('#sp-attach')).not.toBeNull();
    });

    act(() => {
      fireEvent.click(defined(container.querySelector('#sp-attach')));
    });

    await waitFor(() => {
      expect(saveSpy).toHaveBeenCalledTimes(1);
    });
    expect(detachSpy).not.toHaveBeenCalled();
    const savedCfg = saveSpy.mock.calls[0]?.[2] as ScreeningConfig;
    expect(savedCfg.enabled).toBe(false);
  });

  test('Invite: entering emails + send calls inviteScreening with {emails}', async () => {
    spies.push(
      spyOn(screeningModule, 'getScreening').mockResolvedValue(mkConfig({ enabled: true })),
    );
    const inviteSpy = spyOn(screeningModule, 'inviteScreening').mockResolvedValue(undefined);
    spies.push(inviteSpy);

    const { container } = renderPanel(mkRound({ screeningAgentEnabled: true }));

    await waitFor(() => {
      expect(container.querySelector('#sp-invite-emails')).not.toBeNull();
    });

    const emailsInput = defined(
      container.querySelector('#sp-invite-emails'),
    ) as HTMLTextAreaElement;
    act(() => {
      fireEvent.change(emailsInput, {
        target: { value: 'a@example.com, b@example.com' },
      });
    });

    act(() => {
      fireEvent.click(defined(container.querySelector('#sp-invite-send')));
    });

    await waitFor(() => {
      expect(inviteSpy).toHaveBeenCalledTimes(1);
    });
    const body = inviteSpy.mock.calls[0]?.[2] as { emails?: string[] };
    expect(body.emails).toEqual(['a@example.com', 'b@example.com']);
  });
});
