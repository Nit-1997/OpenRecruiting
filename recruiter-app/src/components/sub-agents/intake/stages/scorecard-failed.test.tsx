import { describe, it, expect, mock } from 'bun:test';
import { render, fireEvent, screen, waitFor } from '@testing-library/react';
import { ScorecardFailed } from './scorecard-failed';
import type { IntakeSession } from '@/types/intake';

const SESSION: IntakeSession = {
  id: 'sess-1', requisition_id: 'req-1', user_id: 'u-1', organization_id: 'o-1',
  status: 'submitted', active_modality: null, entry_point: null,
  form_data: { role_name: 'x', experience_min: 0, experience_max: 1, location: 'x', jd_text: null },
  questions_version: 'v1', questions_snapshot: [],
  prefilled_answers: null, current_answers: null, turns: [],
  process_stages: [], process_status: 'failed', process_error: 'Sonnet timeout',
  interview_plan: null,
  created_at: 'x', updated_at: 'y',
};

const ORIGINAL = globalThis.fetch;

describe('ScorecardFailed', () => {
  it('renders error detail', () => {
    render(<ScorecardFailed session={SESSION} onRetried={() => {}} />);
    expect(screen.getByText(/sonnet timeout/i)).toBeTruthy();
  });

  it('Retry calls submitSession and bubbles onRetried on 202', async () => {
    const onRetried = mock(() => {});
    globalThis.fetch = mock(async () => new Response(JSON.stringify({
      session_id: 'sess-1', status: 'submitted',
    }), { status: 202, headers: { 'content-type': 'application/json' } })) as unknown as typeof fetch;
    render(<ScorecardFailed session={SESSION} onRetried={onRetried} />);
    fireEvent.click(screen.getByRole('button', { name: /retry/i }));
    await waitFor(() => expect(onRetried).toHaveBeenCalled());
    globalThis.fetch = ORIGINAL;
  });
});
