import { describe, expect, it } from 'bun:test';
import { render } from '@testing-library/react';
import type { IntakeSession } from '@/types/intake';
import { PlanGenerating } from './plan-generating';

function fakeSession(stages: IntakeSession['process_stages']): IntakeSession {
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
    process_stages: stages,
    process_status: 'running',
    process_error: null,
    interview_plan: null,
    created_at: '2026-05-28T00:00:00Z',
    updated_at: '2026-05-28T00:00:00Z',
  };
}

describe('PlanGenerating', () => {
  it('renders the building-plan headline with the role name', () => {
    const { getByText } = render(<PlanGenerating session={fakeSession([])} />);
    expect(getByText(/building interview plan/i)).toBeTruthy();
    expect(getByText('Senior BE')).toBeTruthy();
  });

  it('shows scorecard stage labels with state driven by process_stages', () => {
    const stages: IntakeSession['process_stages'] = [
      {
        name: 'scorecard_rounds',
        status: 'completed',
        output: null,
        error: null,
        updated_at: null,
      },
      { name: 'scorecard_details', status: 'running', output: null, error: null, updated_at: null },
    ];
    const { getByText } = render(<PlanGenerating session={fakeSession(stages)} />);
    expect(getByText(/structuring interview rounds/i)).toBeTruthy();
    expect(getByText(/rubrics & guidelines/i)).toBeTruthy();
    expect(
      document.getElementById('intake-stage-plan-generating-step-scorecard_rounds')?.getAttribute('data-state'),
    ).toBe('done');
    expect(
      document.getElementById('intake-stage-plan-generating-step-scorecard_details')?.getAttribute('data-state'),
    ).toBe('run');
  });
});
