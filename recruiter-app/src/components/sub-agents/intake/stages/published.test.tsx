import { describe, it, expect, mock } from 'bun:test';
import { render, fireEvent, screen } from '@testing-library/react';
import { Published } from './published';
import type { IntakeSession } from '@/types/intake';

const SESSION: IntakeSession = {
  id: 'sess-1', requisition_id: 'req-1', user_id: 'u-1', organization_id: 'o-1',
  status: 'published', active_modality: null, entry_point: null,
  form_data: { role_name: 'Senior BE', experience_min: 5, experience_max: 8, location: 'NYC', jd_text: null },
  questions_version: 'v1', questions_snapshot: [],
  prefilled_answers: null, current_answers: null, turns: [],
  process_stages: [], process_status: 'idle', process_error: null,
  interview_plan: { rounds: [] },
  created_at: 'x', updated_at: 'y',
};

describe('Published', () => {
  it('renders success message with role name', () => {
    const { getByText } = render(<Published session={SESSION} redirectUrl="/view/roles/req-1" onOpen={() => {}} />);
    expect(getByText(/published/i)).toBeTruthy();
    expect(getByText(/Senior BE/)).toBeTruthy();
  });

  it('Open in Roles button calls onOpen with the redirect url', () => {
    const onOpen = mock((_u: string) => {});
    render(<Published session={SESSION} redirectUrl="/view/roles/req-1" onOpen={onOpen} />);
    fireEvent.click(screen.getByRole('button', { name: /open in roles/i }));
    expect(onOpen).toHaveBeenCalledWith('/view/roles/req-1');
  });
});
