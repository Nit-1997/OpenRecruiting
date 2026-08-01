import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { IntakeSession, InterviewPlan } from '@/types/intake';
import { PlanEditing } from './plan-editing';

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
  ],
};

function session(plan: InterviewPlan): IntakeSession {
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
    interview_plan: plan,
    created_at: 'x',
    updated_at: 'y',
  };
}

const ORIGINAL_FETCH = globalThis.fetch;

describe('PlanEditing', () => {
  beforeEach(() => {
    globalThis.fetch = ORIGINAL_FETCH;
  });
  afterEach(() => {
    globalThis.fetch = ORIGINAL_FETCH;
  });

  it('renders the captured-intake banner + editor with rounds', () => {
    render(<PlanEditing session={session(PLAN)} onPublished={() => {}} />);
    expect(screen.getByText(/intake captured/i)).toBeTruthy();
    expect(screen.getAllByText('Coding').length).toBeGreaterThan(0);
  });

  it('Publish click calls publishSession + onPublished with response', async () => {
    const onPublished = mock((_r: { redirect_url: string; requisition_id: string }) => {});
    globalThis.fetch = mock(
      async () =>
        new Response(
          JSON.stringify({
            session_id: 'sess-1',
            requisition_id: 'req-1',
            redirect_url: '/view/roles/req-1',
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        ),
    ) as unknown as typeof fetch;
    render(<PlanEditing session={session(PLAN)} onPublished={onPublished} />);
    fireEvent.click(screen.getByRole('button', { name: /^publish/i }));
    await waitFor(() => expect(onPublished).toHaveBeenCalled());
    const arg = onPublished.mock.calls[0]![0]!;
    expect(arg.redirect_url).toBe('/view/roles/req-1');
    expect(arg.requisition_id).toBe('req-1');
  });

  it('surfaces publish error inline', async () => {
    globalThis.fetch = mock(
      async () =>
        new Response(JSON.stringify({ detail: 'Round 1 missing name' }), {
          status: 422,
          headers: { 'content-type': 'application/json' },
        }),
    ) as unknown as typeof fetch;
    render(<PlanEditing session={session(PLAN)} onPublished={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: /^publish/i }));
    await waitFor(() => expect(screen.getByText(/round 1 missing name/i)).toBeTruthy());
  });
});
