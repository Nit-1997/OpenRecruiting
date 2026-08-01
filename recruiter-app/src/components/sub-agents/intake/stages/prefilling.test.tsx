import { describe, expect, test } from 'bun:test';
import { render } from '@testing-library/react';
import type { IntakeSession } from '@/types/intake';
import { PrefillingStage } from './prefilling';

function fakeSession(over: Partial<IntakeSession> = {}): IntakeSession {
  return {
    id: 'sess-1',
    requisition_id: 'r',
    user_id: 'u',
    organization_id: 'o',
    status: 'prefilling',
    active_modality: null,
    entry_point: null,
    form_data: {
      role_name: 'Staff Engineer',
      experience_min: 5,
      experience_max: 10,
      location: 'NYC',
      jd_text: null,
    },
    questions_version: 'v1',
    questions_snapshot: [],
    prefilled_answers: null,
    current_answers: null,
    turns: [],
    process_stages: [],
    process_status: 'running',
    process_error: null,
    interview_plan: null,
    created_at: '2026-05-28T00:00:00Z',
    updated_at: '2026-05-28T00:00:00Z',
    ...over,
  };
}

describe('PrefillingStage', () => {
  test('renders the role name as the card title', () => {
    const { container } = render(<PrefillingStage id="pf" session={fakeSession()} />);
    expect(container.textContent ?? '').toContain('Staff Engineer');
  });

  test('renders "Gathering context" eyebrow', () => {
    const { container } = render(<PrefillingStage id="pf" session={fakeSession()} />);
    expect(container.textContent ?? '').toMatch(/gathering context/i);
  });

  test('check_context step has data-state="done" when completed', () => {
    render(
      <PrefillingStage
        id="pf"
        session={fakeSession({
          process_stages: [
            {
              name: 'check_context',
              status: 'completed',
              output: null,
              error: null,
              updated_at: null,
            },
            { name: 'parse_jd', status: 'running', output: null, error: null, updated_at: null },
            {
              name: 'query_cortex',
              status: 'pending',
              output: null,
              error: null,
              updated_at: null,
            },
          ],
        })}
      />,
    );
    expect(document.getElementById('pf-step-check_context')?.dataset.state).toBe('done');
  });

  test('parse_jd step has data-state="run" when running', () => {
    render(
      <PrefillingStage
        id="pf"
        session={fakeSession({
          process_stages: [
            {
              name: 'check_context',
              status: 'completed',
              output: null,
              error: null,
              updated_at: null,
            },
            { name: 'parse_jd', status: 'running', output: null, error: null, updated_at: null },
            {
              name: 'query_cortex',
              status: 'pending',
              output: null,
              error: null,
              updated_at: null,
            },
          ],
        })}
      />,
    );
    expect(document.getElementById('pf-step-parse_jd')?.dataset.state).toBe('run');
  });

  test('query_cortex step has data-state="wait" when pending', () => {
    render(
      <PrefillingStage
        id="pf"
        session={fakeSession({
          process_stages: [
            {
              name: 'check_context',
              status: 'completed',
              output: null,
              error: null,
              updated_at: null,
            },
            { name: 'parse_jd', status: 'running', output: null, error: null, updated_at: null },
            {
              name: 'query_cortex',
              status: 'pending',
              output: null,
              error: null,
              updated_at: null,
            },
          ],
        })}
      />,
    );
    expect(document.getElementById('pf-step-query_cortex')?.dataset.state).toBe('wait');
  });

  test('only shows steps present in process_stages (scorecard stages excluded)', () => {
    const { container } = render(
      <PrefillingStage
        id="pf"
        session={fakeSession({
          process_stages: [
            {
              name: 'check_context',
              status: 'completed',
              output: null,
              error: null,
              updated_at: null,
            },
            {
              name: 'scorecard_rounds',
              status: 'running',
              output: null,
              error: null,
              updated_at: null,
            },
          ],
        })}
      />,
    );
    expect(document.getElementById('pf-step-check_context')).not.toBeNull();
    expect(document.getElementById('pf-step-scorecard_rounds')).toBeNull();
    expect(container.querySelectorAll('li').length).toBe(1);
  });

  test('failed stage renders as wait (no crash)', () => {
    render(
      <PrefillingStage
        id="pf"
        session={fakeSession({
          process_stages: [
            {
              name: 'check_context',
              status: 'failed',
              output: null,
              error: 'timeout',
              updated_at: null,
            },
          ],
        })}
      />,
    );
    expect(document.getElementById('pf-step-check_context')?.dataset.state).toBe('wait');
  });

  test('falls back to "Your role" when role_name is empty', () => {
    const { container } = render(
      <PrefillingStage
        id="pf"
        session={fakeSession({
          form_data: {
            role_name: '',
            experience_min: 0,
            experience_max: 0,
            location: '',
            jd_text: null,
          },
        })}
      />,
    );
    expect(container.textContent ?? '').toContain('Your role');
  });
});
