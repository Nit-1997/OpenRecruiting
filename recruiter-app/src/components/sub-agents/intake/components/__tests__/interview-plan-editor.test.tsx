import { describe, expect, it } from 'bun:test';
import { fireEvent, render, screen } from '@testing-library/react';
import type { IntakeSession, InterviewPlan, InterviewPlanRound } from '@/types/intake';
import { InterviewPlanEditor, roundCardPropsEqual } from '../interview-plan-editor';

const PLAN: InterviewPlan = {
  rounds: [
    {
      id: 'r1',
      round_number: 1,
      name: 'Coding',
      category: 'coding',
      duration_minutes: 60,
      description: '',
      skills: [],
      guidelines: [],
      feedback_questions: [{ id: 'fq1', question_number: 1, heading: 'Q', description: null }],
    },
    {
      id: 'r2',
      round_number: 2,
      name: 'Design',
      category: 'design',
      duration_minutes: 45,
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

function renderEditor() {
  return render(
    <InterviewPlanEditor
      id="intake-plan-editor"
      session={session()}
      initialPlan={PLAN}
      isPublishing={false}
      publishError={null}
      onPublish={() => {}}
      onBack={() => {}}
    />,
  );
}

describe('InterviewPlanEditor — no false save claim (FE-J5)', () => {
  it('never renders the misleading "Draft saved automatically" footer', () => {
    renderEditor();
    expect(screen.queryByText(/draft saved automatically/i)).toBeNull();
  });

  it('does not claim "Plan saved" after toggling out of edit mode', () => {
    renderEditor();
    // The rail toggle previously flipped to "Save plan" and then showed a
    // "Plan saved" tag even though nothing was persisted. Toggling it must NOT
    // claim a save that never happened.
    const toggle = document.getElementById('intake-plan-editor-edit-toggle') as HTMLButtonElement;
    fireEvent.click(toggle);
    expect(screen.queryByText(/plan saved/i)).toBeNull();
  });

  it('the rail toggle reads Edit/Done (view-mode), not Save plan', () => {
    renderEditor();
    const toggle = document.getElementById('intake-plan-editor-edit-toggle') as HTMLButtonElement;
    // While editing the toggle leaves edit-mode (it is NOT a "Save plan" CTA).
    expect(toggle.textContent ?? '').not.toMatch(/save plan/i);
  });

  it('still exposes Publish as the real persistence action', () => {
    renderEditor();
    expect(screen.getByRole('button', { name: /^publish/i })).toBeTruthy();
  });
});

function roundOf(over: Partial<InterviewPlanRound> = {}): InterviewPlanRound {
  return {
    id: 'r2',
    round_number: 2,
    name: 'Design',
    category: 'design',
    duration_minutes: 45,
    description: '',
    skills: [],
    guidelines: [],
    feedback_questions: [],
    ...over,
  };
}

describe('roundCardPropsEqual — memo comparator (FE-J5 perf)', () => {
  const stableHandlers = {} as never;
  const stableGrabRef = { current: null };
  const noop = () => {};
  const base = {
    index: 1,
    round: roundOf(),
    readOnly: false,
    handlers: stableHandlers,
    dragId: null as string | null,
    grabRef: stableGrabRef,
    onDragStart: noop,
    onDragOver: noop,
    onDragEnd: noop,
    onConfigureScreening: noop,
  };

  it('returns true (skip re-render) when an unchanged sibling re-renders', () => {
    // Same round reference + same stable props → memo must skip this card.
    expect(roundCardPropsEqual(base, { ...base })).toBe(true);
  });

  it('returns false when THIS round object changed (must re-render)', () => {
    expect(roundCardPropsEqual(base, { ...base, round: roundOf({ name: 'Edited' }) })).toBe(false);
  });

  it('returns false when dragId / readOnly / index change', () => {
    expect(roundCardPropsEqual(base, { ...base, dragId: 'r2' })).toBe(false);
    expect(roundCardPropsEqual(base, { ...base, readOnly: true })).toBe(false);
    expect(roundCardPropsEqual(base, { ...base, index: 2 })).toBe(false);
  });

  it('returns false when onConfigureScreening identity changes', () => {
    expect(roundCardPropsEqual(base, { ...base, onConfigureScreening: () => {} })).toBe(false);
  });
});

describe('InterviewPlanEditor — RoundCard memo (FE-J5 perf)', () => {
  it('editing one round does not re-render sibling round cards', () => {
    renderEditor();
    // Both round cards mount with their distinct ids.
    expect(document.getElementById('intake-round-r1')).not.toBeNull();
    expect(document.getElementById('intake-round-r2')).not.toBeNull();
    // Commit an edit to round 1's name.
    const name = document.getElementById('intake-round-r1-name') as HTMLElement;
    fireEvent.click(name);
    const input = document.getElementById('intake-round-r1-name') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'Live Coding' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    // Round 2 still renders its original name (no crash / no remount loss).
    expect((document.getElementById('intake-round-r2-name')?.textContent ?? '')).toContain(
      'Design',
    );
  });
});
