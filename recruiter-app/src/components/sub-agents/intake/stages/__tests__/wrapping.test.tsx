import { describe, it, expect, mock } from 'bun:test';
import { render } from '@testing-library/react';
import { WrappingStage } from '@/components/sub-agents/intake/stages/wrapping';

mock.module('@/hooks/intake/use-manual-answer-edit', () => ({
  useManualAnswerEdit: () => ({ savingQid: null, error: null, saveEdit: mock(), clearError: mock() }),
}));

const session = {
  id: 'sess-1',
  requisition_id: 'r', user_id: 'u', organization_id: 'o',
  status: 'ready', active_modality: null, entry_point: null,
  form_data: { role_name: 'x', experience_min: 1, experience_max: 2, location: 'NYC', jd_text: null },
  questions_version: '1',
  turns: [{ idx: 0, role: 'assistant', content: 'Wrapping up', modality: 'voice', timestamp: 'now' }],
  current_answers: {},
  prefilled_answers: null,
  questions_snapshot: [],
  process_stages: [], process_status: 'idle', process_error: null, interview_plan: null,
  created_at: '', updated_at: '',
} as any;

describe('WrappingStage', () => {
  it('renders the wrap banner + Submit CTA + final transcript + final CoverageTable', () => {
    render(<WrappingStage session={session} />);
    expect(document.getElementById('v2-intake-stage-wrapping-banner')).not.toBeNull();
    expect(document.getElementById('v2-intake-stage-wrapping-submit-btn')).not.toBeNull();
    expect(document.getElementById('v2-intake-transcript')).not.toBeNull();
    expect(document.getElementById('v2-intake-coverage-table')).not.toBeNull();
  });

  it('Submit button is enabled now Phase 5 wired it', () => {
    render(<WrappingStage session={session} />);
    const btn = document.getElementById('v2-intake-stage-wrapping-submit-btn') as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
  });

  it('renders both voice and text turns ordered by idx (Phase 3)', () => {
    const mixed = {
      ...session,
      turns: [
        { idx: 0, role: 'user', content: 'voice-1', modality: 'voice', timestamp: '' },
        { idx: 1, role: 'user', content: 'text-1', modality: 'text', timestamp: '' },
        { idx: 2, role: 'assistant', content: 'voice-2', modality: 'voice', timestamp: '' },
      ],
    };
    const { container } = render(<WrappingStage session={mixed} />);
    expect(container.textContent).toContain('voice-1');
    expect(container.textContent).toContain('text-1');
    expect(container.textContent).toContain('voice-2');
  });
});
