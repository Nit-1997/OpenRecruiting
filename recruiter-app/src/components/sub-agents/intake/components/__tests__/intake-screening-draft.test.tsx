// Draft screening config during intake (pre-publish).
//
// Drives the FULL InterviewPlanEditor: an eligible round surfaces the "Set up
// screening" nudge, generate calls generateScreeningDraft + renders the returned
// questions, enabling + Done writes `screening` onto the round, and the publish
// payload carries `round.screening` in the snake_case wire shape publish reads.
//
// We spy on the LIVE `@/services/screening` exports (restored in afterEach) — bun
// mock.module is process-wide + unrestorable (same pattern as the config-panel test).

import { afterEach, beforeEach, describe, expect, spyOn, test } from 'bun:test';
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import { ToastProvider } from '@/components/ui/toast';
import type { ScreeningQuestion } from '@/services/screening';
import * as screeningModule from '@/services/screening';
import type { IntakeSession, InterviewPlan } from '@/types/intake';
import { InterviewPlanEditor } from '../interview-plan-editor';

function mkQuestion(over: Partial<ScreeningQuestion> = {}): ScreeningQuestion {
  return {
    orderIndex: 0,
    title: 'Metric ownership',
    prompt: 'Walk me through a metric you owned.',
    probe: 'What did you do when it dipped?',
    signal: 'execution',
    dimension: 'ownership',
    durationMinutes: 5,
    ...over,
  };
}

// Round 1 is an eligible "Recruiter Screen" (culture). Round 2 is design (never
// eligible) — so exactly one nudge should appear.
const PLAN: InterviewPlan = {
  rounds: [
    {
      id: 'r1',
      round_number: 1,
      name: 'Recruiter Screen',
      category: 'culture',
      duration_minutes: 30,
      description: '',
      skills: ['communication'],
      guidelines: [],
      feedback_questions: [{ id: 'fq1', question_number: 1, heading: 'Q', description: null }],
    },
    {
      id: 'r2',
      round_number: 2,
      name: 'System Design',
      category: 'design',
      duration_minutes: 60,
      description: '',
      skills: [],
      guidelines: [],
      feedback_questions: [{ id: 'fq2', question_number: 1, heading: 'Q2', description: null }],
    },
  ],
};

function session(): IntakeSession {
  return {
    id: 'sess-1',
    requisition_id: 'req-1',
    user_id: 'u-1',
    organization_id: 'o-1',
    status: 'submitted',
    active_modality: null,
    entry_point: null,
    form_data: {
      role_name: 'Senior BE',
      experience_min: 5,
      experience_max: 8,
      location: 'NYC',
      jd_text: null,
    },
    questions_version: 'v1',
    questions_snapshot: [],
    prefilled_answers: null,
    current_answers: null,
    turns: [],
    process_stages: [],
    process_status: 'idle',
    process_error: null,
    interview_plan: PLAN,
    created_at: 'x',
    updated_at: 'y',
  };
}

const spies: Array<ReturnType<typeof spyOn>> = [];
afterEach(() => {
  for (const s of spies) s.mockRestore();
  spies.length = 0;
  cleanup();
});
beforeEach(() => {
  spies.length = 0;
});

function renderEditor(onPublish: (p: InterviewPlan) => void = () => {}) {
  return render(
    <ToastProvider>
      <InterviewPlanEditor
        id="intake-plan-editor"
        session={session()}
        initialPlan={PLAN}
        isPublishing={false}
        publishError={null}
        onPublish={onPublish}
        onBack={() => {}}
      />
    </ToastProvider>,
  );
}

describe('intake draft screening', () => {
  test('eligible round shows the "Set up screening" nudge; ineligible does not', () => {
    renderEditor();
    expect(document.getElementById('intake-round-r1-screening-nudge')).not.toBeNull();
    expect(document.getElementById('intake-round-r2-screening-nudge')).toBeNull();
  });

  test('generate calls generateScreeningDraft and renders the returned questions', async () => {
    const genSpy = spyOn(screeningModule, 'generateScreeningDraft').mockResolvedValue([
      mkQuestion({ title: 'Pricing instinct', orderIndex: 0 }),
      mkQuestion({ title: 'Conflict story', orderIndex: 1 }),
    ]);
    spies.push(genSpy);

    renderEditor();

    // Open the panel from the nudge.
    const nudge = document.getElementById('intake-round-r1-screening-nudge') as HTMLButtonElement;
    act(() => fireEvent.click(nudge));

    const generate = document.getElementById(
      'intake-plan-editor-screening-panel-generate',
    ) as HTMLButtonElement;
    act(() => fireEvent.click(generate));

    await waitFor(() => {
      expect(document.getElementById('intake-plan-editor-screening-panel-q-0')).not.toBeNull();
    });
    expect(genSpy).toHaveBeenCalledTimes(1);
    // Body carried the round's context.
    const firstCall = genSpy.mock.calls[0] ?? [];
    expect(firstCall[0]).toBe('sess-1');
    expect(firstCall[1]).toMatchObject({ roundName: 'Recruiter Screen', category: 'culture' });
    // Two cards rendered.
    expect(document.getElementById('intake-plan-editor-screening-panel-q-1')).not.toBeNull();
  });

  test('derive persona calls derivePersonaDraft and stores the snapshot in the publish payload', async () => {
    spies.push(
      spyOn(screeningModule, 'derivePersonaDraft').mockResolvedValue({
        personaId: 'p1',
        composedText: 'Tone & rapport: warm\n\nNON-NEGOTIABLE RULES:\n- be fair',
        dimensions: [{ key: 'tone_rapport', value: 'warm', confidence: 0.8, source: 'cortex' }],
        snapshot: {
          dimensions: [{ key: 'tone_rapport', value: 'warm', confidence: 0.8, source: 'cortex' }],
          text: 'Tone & rapport: warm\n\nNON-NEGOTIABLE RULES:\n- be fair',
        },
      }),
    );

    let published: InterviewPlan | null = null;
    renderEditor((p) => {
      published = p;
    });

    const nudge = document.getElementById('intake-round-r1-screening-nudge') as HTMLButtonElement;
    act(() => fireEvent.click(nudge));

    const derive = document.getElementById(
      'intake-plan-editor-screening-panel-derive',
    ) as HTMLButtonElement;
    act(() => fireEvent.click(derive));

    // The derived persona dimension card renders.
    await waitFor(() => {
      expect(
        document.getElementById('intake-plan-editor-screening-panel-dim-tone_rapport'),
      ).not.toBeNull();
    });

    // Enable so the round is materialized at publish, then publish.
    const enable = document.getElementById(
      'intake-plan-editor-screening-panel-enable',
    ) as HTMLButtonElement;
    act(() => fireEvent.click(enable));
    const done = document.getElementById(
      'intake-plan-editor-screening-panel-done',
    ) as HTMLButtonElement;
    act(() => fireEvent.click(done));
    const publish = document.getElementById('intake-plan-editor-publish') as HTMLButtonElement;
    act(() => fireEvent.click(publish));

    const plan = published as unknown as InterviewPlan;
    const r1 = plan.rounds[0] as unknown as Record<string, unknown>;
    const screening = r1.screening as Record<string, unknown>;
    const snapshot = screening.persona_snapshot as Record<string, unknown>;
    expect(snapshot).toBeDefined();
    expect(snapshot.text).toContain('NON-NEGOTIABLE RULES');
    expect((snapshot.dimensions as unknown[]).length).toBe(1);
  });

  test('enable + Done writes screening; publish payload carries round.screening (wire shape)', async () => {
    spies.push(
      spyOn(screeningModule, 'generateScreeningDraft').mockResolvedValue([
        mkQuestion({ title: 'Pricing instinct', orderIndex: 0 }),
      ]),
    );

    let published: InterviewPlan | null = null;
    renderEditor((p) => {
      published = p;
    });

    const nudge = document.getElementById('intake-round-r1-screening-nudge') as HTMLButtonElement;
    act(() => fireEvent.click(nudge));

    const generate = document.getElementById(
      'intake-plan-editor-screening-panel-generate',
    ) as HTMLButtonElement;
    act(() => fireEvent.click(generate));
    await waitFor(() => {
      expect(document.getElementById('intake-plan-editor-screening-panel-q-0')).not.toBeNull();
    });

    // Enable ("OpenRecruiting takes this round").
    const enable = document.getElementById(
      'intake-plan-editor-screening-panel-enable',
    ) as HTMLButtonElement;
    act(() => fireEvent.click(enable));

    // Close via Done.
    const done = document.getElementById(
      'intake-plan-editor-screening-panel-done',
    ) as HTMLButtonElement;
    act(() => fireEvent.click(done));

    // The round-card badge now reflects the configured round.
    expect(document.getElementById('intake-round-r1-screening-badge')).not.toBeNull();
    // The eligibility nudge is gone (configured wins).
    expect(document.getElementById('intake-round-r1-screening-nudge')).toBeNull();

    // Publish carries the wire-shaped screening on round 1, nothing on round 2.
    const publish = document.getElementById('intake-plan-editor-publish') as HTMLButtonElement;
    act(() => fireEvent.click(publish));

    expect(published).not.toBeNull();
    const plan = published as unknown as InterviewPlan;
    const r1 = plan.rounds[0] as unknown as Record<string, unknown>;
    const screening = r1.screening as Record<string, unknown>;
    expect(screening).toBeDefined();
    expect(screening.enabled).toBe(true);
    // Wire shape: snake_case keys.
    expect(screening.follow_up_style).toBeDefined();
    expect(screening.validity_days).toBeDefined();
    const qs = screening.questions as Array<Record<string, unknown>>;
    expect(qs).toHaveLength(1);
    const q0 = qs[0] ?? {};
    expect(q0.order_index).toBe(0);
    expect(q0.duration_minutes).toBe(5);
    // Round 2 has no screening key.
    const r2 = plan.rounds[1] as unknown as Record<string, unknown>;
    expect(r2.screening).toBeUndefined();
  });
});
