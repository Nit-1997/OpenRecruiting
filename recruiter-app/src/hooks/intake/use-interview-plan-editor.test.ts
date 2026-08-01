import { describe, it, expect } from 'bun:test';
import { renderHook, act } from '@testing-library/react';
import { useInterviewPlanEditor } from './use-interview-plan-editor';
import type { InterviewPlan } from '@/types/intake';

function seed(): InterviewPlan {
  return {
    rounds: [
      {
        id: 'r1', round_number: 1, name: 'Coding', category: 'coding',
        duration_minutes: 60, description: 'live coding', skills: ['Python'],
        guidelines: [{ title: 'Be specific', description: 'push for code' }],
        feedback_questions: [
          { id: 'fq1', question_number: 1, heading: 'Quality', description: 'readable' },
        ],
      },
      {
        id: 'r2', round_number: 2, name: 'Design', category: 'design',
        duration_minutes: 60, description: 'whiteboard', skills: ['systems'],
        guidelines: [],
        feedback_questions: [
          { id: 'fq2', question_number: 1, heading: 'Tradeoffs', description: null },
        ],
      },
    ],
  };
}

describe('useInterviewPlanEditor', () => {
  it('seeds working copy from initial plan and is not dirty', () => {
    const { result } = renderHook(() => useInterviewPlanEditor(seed()));
    expect(result.current.plan.rounds).toHaveLength(2);
    expect(result.current.isDirty).toBe(false);
    expect(result.current.canPublish).toBe(true);
  });

  it('updateRound marks dirty and pushes undo entry', () => {
    const { result } = renderHook(() => useInterviewPlanEditor(seed()));
    act(() => result.current.updateRound('r1', { name: 'Live Coding' }));
    expect(result.current.plan.rounds[0]!.name).toBe('Live Coding');
    expect(result.current.isDirty).toBe(true);
    expect(result.current.canUndo).toBe(true);
  });

  it('undo restores prior value and pops the stack', () => {
    const { result } = renderHook(() => useInterviewPlanEditor(seed()));
    act(() => result.current.updateRound('r1', { name: 'Live Coding' }));
    act(() => result.current.undo());
    expect(result.current.plan.rounds[0]!.name).toBe('Coding');
    expect(result.current.canUndo).toBe(false);
  });

  it('reorderRounds swaps order and updates round_number contiguously', () => {
    const { result } = renderHook(() => useInterviewPlanEditor(seed()));
    act(() => result.current.reorderRounds(0, 1));
    expect(result.current.plan.rounds[0]!.id).toBe('r2');
    expect(result.current.plan.rounds[0]!.round_number).toBe(1);
    expect(result.current.plan.rounds[1]!.id).toBe('r1');
    expect(result.current.plan.rounds[1]!.round_number).toBe(2);
  });

  it('addFeedbackQuestion + removeFeedbackQuestion both undoable', () => {
    const { result } = renderHook(() => useInterviewPlanEditor(seed()));
    act(() => result.current.addFeedbackQuestion('r2', { heading: 'Communication', description: null }));
    expect(result.current.plan.rounds[1]!.feedback_questions).toHaveLength(2);
    const newId = result.current.plan.rounds[1]!.feedback_questions[1]!.id;
    act(() => result.current.removeFeedbackQuestion('r2', newId));
    expect(result.current.plan.rounds[1]!.feedback_questions).toHaveLength(1);
    act(() => result.current.undo());
    expect(result.current.plan.rounds[1]!.feedback_questions).toHaveLength(2);
    act(() => result.current.undo());
    expect(result.current.plan.rounds[1]!.feedback_questions).toHaveLength(1);
  });

  it('addGuideline + removeGuideline both undoable', () => {
    const { result } = renderHook(() => useInterviewPlanEditor(seed()));
    act(() => result.current.addGuideline('r2', { title: 'New', description: 'desc' }));
    expect(result.current.plan.rounds[1]!.guidelines).toHaveLength(1);
    act(() => result.current.undo());
    expect(result.current.plan.rounds[1]!.guidelines).toHaveLength(0);
  });

  it('canPublish false when any round has empty name', () => {
    const { result } = renderHook(() => useInterviewPlanEditor(seed()));
    act(() => result.current.updateRound('r1', { name: '   ' }));
    expect(result.current.canPublish).toBe(false);
    expect(result.current.violations).toContainEqual({
      roundId: 'r1', kind: 'missing_name',
    });
  });

  it('canPublish false when any round has zero feedback questions', () => {
    const { result } = renderHook(() => useInterviewPlanEditor(seed()));
    act(() => result.current.removeFeedbackQuestion('r1', 'fq1'));
    expect(result.current.canPublish).toBe(false);
    expect(result.current.violations).toContainEqual({
      roundId: 'r1', kind: 'no_feedback_questions',
    });
  });

  it('reset re-seeds working copy and clears undo stack', () => {
    const initial = seed();
    const { result } = renderHook(
      ({ p }: { p: InterviewPlan }) => useInterviewPlanEditor(p),
      { initialProps: { p: initial } },
    );
    act(() => result.current.updateRound('r1', { name: 'X' }));
    const fresh = seed();
    fresh.rounds[0]!.name = 'Server-Updated';
    act(() => result.current.reset(fresh));
    expect(result.current.plan.rounds[0]!.name).toBe('Server-Updated');
    expect(result.current.isDirty).toBe(false);
    expect(result.current.canUndo).toBe(false);
  });
});
