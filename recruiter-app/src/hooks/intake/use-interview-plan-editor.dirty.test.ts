import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'bun:test';
import type { InterviewPlan } from '@/types/intake';
import { useInterviewPlanEditor } from './use-interview-plan-editor';

function seed(): InterviewPlan {
  return {
    rounds: [
      {
        id: 'r1',
        round_number: 1,
        name: 'Coding',
        category: 'coding',
        duration_minutes: 60,
        description: 'live coding',
        skills: ['Python'],
        guidelines: [],
        feedback_questions: [{ id: 'fq1', question_number: 1, heading: 'Quality', description: null }],
      },
    ],
  };
}

// isDirty is now a mutation-tracked FLAG, not a per-render JSON.stringify of the
// whole plan. The observable consequence: once you've mutated, the editor stays
// dirty even if you happen to type the value back to its original — because a
// mutation DID happen (the undo stack records it). A stringify-based isDirty
// would (wrongly) report clean again on an edit-back.
describe('useInterviewPlanEditor isDirty — flag-based (FE-J5 perf)', () => {
  it('starts clean', () => {
    const { result } = renderHook(() => useInterviewPlanEditor(seed()));
    expect(result.current.isDirty).toBe(false);
  });

  it('flips dirty on the first mutation', () => {
    const { result } = renderHook(() => useInterviewPlanEditor(seed()));
    act(() => result.current.updateRound('r1', { name: 'Live Coding' }));
    expect(result.current.isDirty).toBe(true);
  });

  it('stays dirty even after editing a field back to its original value', () => {
    const { result } = renderHook(() => useInterviewPlanEditor(seed()));
    act(() => result.current.updateRound('r1', { name: 'Live Coding' }));
    act(() => result.current.updateRound('r1', { name: 'Coding' }));
    // Plan content matches the seed again, but a mutation occurred → still dirty.
    expect(result.current.plan.rounds[0]!.name).toBe('Coding');
    expect(result.current.isDirty).toBe(true);
  });

  it('reset clears the dirty flag', () => {
    const { result } = renderHook(() => useInterviewPlanEditor(seed()));
    act(() => result.current.updateRound('r1', { name: 'X' }));
    act(() => result.current.reset(seed()));
    expect(result.current.isDirty).toBe(false);
  });
});
