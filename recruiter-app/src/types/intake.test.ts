import { describe, expect, test } from 'bun:test';
import {
  type AnswerState,
  type IntakeSession,
  type IntakeStage,
  type ProcessStage,
  type QuestionId,
  type SessionListItem,
  isIntakeStage,
  isProcessStage,
  isSessionListItem,
} from './intake';

describe('intake type guards', () => {
  test('isIntakeStage accepts every phase-1 stage', () => {
    const stages: IntakeStage[] = [
      'intake_form',
      'prefilling',
      'ready_choose_modality',
      'prefill_failed',
    ];
    for (const s of stages) expect(isIntakeStage(s)).toBe(true);
  });

  test('isIntakeStage rejects unknown', () => {
    expect(isIntakeStage('nope')).toBe(false);
    expect(isIntakeStage(undefined)).toBe(false);
  });

  test('isProcessStage validates shape', () => {
    const ok: ProcessStage = {
      name: 'check_context',
      status: 'completed',
      output: null,
      error: null,
      updated_at: '2026-05-28T00:00:00Z',
    };
    expect(isProcessStage(ok)).toBe(true);
    expect(isProcessStage({ name: 'x' })).toBe(false);
    expect(isProcessStage(null)).toBe(false);
  });

  test('isSessionListItem accepts a complete row', () => {
    const item: SessionListItem = {
      session_id: 'abc',
      requisition_id: 'def',
      title: 'Intake: x',
      display_status: 'incomplete',
      detail_status: 'created',
      last_activity_at: '2026-05-28T00:00:00Z',
      active_modality: null,
      resume_url: '/intake/sessions/abc',
      covered: 0,
      total: 9,
      rounds_count: 0,
      total_minutes: 0,
      candidates_count: 0,
    };
    expect(isSessionListItem(item)).toBe(true);
  });

  test('QuestionId union has 9 ids', () => {
    const all: QuestionId[] = [
      'q1_role_overview',
      'q2_rounds',
      'q3_focus_areas',
      'q4_must_haves',
      'q5_nice_to_haves',
      'q6_cultural_fit',
      'q7_team_structure',
      'q8_red_flags',
      'q9_anything_else',
    ];
    expect(all.length).toBe(9);
  });

  test('AnswerState manual_edit fields are optional', () => {
    const a: AnswerState = {
      status: 'untouched',
      text: null,
      prefilled_text: null,
      extraction_confidence: 'none',
      sources: [],
      turns_addressed: [],
    };
    expect(a.manual_edit).toBeUndefined();
  });

  test('IntakeSession includes process_status', () => {
    const s: IntakeSession = {
      id: 'x',
      requisition_id: 'y',
      user_id: 'u',
      organization_id: 'o',
      status: 'created',
      active_modality: null,
      entry_point: null,
      form_data: { role_name: 'r', experience_min: 0, experience_max: 5, location: 'NYC', jd_text: null },
      questions_version: 'v1',
      questions_snapshot: [],
      prefilled_answers: null,
      current_answers: null,
      turns: [],
      process_stages: [],
      process_status: 'idle',
      process_error: null,
      interview_plan: null,
      created_at: '2026-05-28T00:00:00Z',
      updated_at: '2026-05-28T00:00:00Z',
    };
    expect(s.process_status).toBe('idle');
  });
});
