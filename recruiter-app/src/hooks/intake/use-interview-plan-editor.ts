'use client';

import { useCallback, useMemo, useRef, useState } from 'react';
import type {
  FeedbackQuestion,
  Guideline,
  InterviewPlan,
  InterviewPlanRound,
  RoundScreening,
} from '@/types/intake';

type UndoAction = () => InterviewPlan;

export type PublishViolation =
  | { roundId: string; kind: 'missing_name' }
  | { roundId: string; kind: 'no_feedback_questions' };

export interface UseInterviewPlanEditor {
  plan: InterviewPlan;
  isDirty: boolean;
  canUndo: boolean;
  canPublish: boolean;
  violations: PublishViolation[];
  updateRound: (roundId: string, patch: Partial<InterviewPlanRound>) => void;
  removeRound: (roundId: string) => void;
  reorderRounds: (from: number, to: number) => void;
  addGuideline: (roundId: string, g: Guideline) => void;
  updateGuideline: (roundId: string, index: number, patch: Partial<Guideline>) => void;
  removeGuideline: (roundId: string, index: number) => void;
  addFeedbackQuestion: (
    roundId: string,
    q: Omit<FeedbackQuestion, 'id' | 'question_number'>,
  ) => void;
  updateFeedbackQuestion: (
    roundId: string,
    questionId: string,
    patch: Partial<FeedbackQuestion>,
  ) => void;
  removeFeedbackQuestion: (roundId: string, questionId: string) => void;
  setRoundScreening: (roundId: string, screening: RoundScreening | undefined) => void;
  undo: () => void;
  reset: (next: InterviewPlan) => void;
}

function cloneScreening(s: RoundScreening): RoundScreening {
  return {
    ...s,
    questions: s.questions.map((q) => ({ ...q })),
    ...(s.personaSnapshot
      ? {
          personaSnapshot: {
            text: s.personaSnapshot.text,
            dimensions: s.personaSnapshot.dimensions.map((d) => ({ ...d })),
          },
        }
      : {}),
  };
}

function cloneRound(r: InterviewPlanRound): InterviewPlanRound {
  return {
    ...r,
    skills: [...r.skills],
    guidelines: r.guidelines.map((g) => ({ ...g })),
    feedback_questions: r.feedback_questions.map((q) => ({ ...q })),
    ...(r.screening ? { screening: cloneScreening(r.screening) } : {}),
  };
}

function clonePlan(p: InterviewPlan): InterviewPlan {
  return { rounds: p.rounds.map(cloneRound) };
}

function renumber(rounds: InterviewPlanRound[]): InterviewPlanRound[] {
  return rounds.map((r, i) => ({ ...r, round_number: i + 1 }));
}

function genId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

export function useInterviewPlanEditor(initial: InterviewPlan): UseInterviewPlanEditor {
  const [plan, setPlan] = useState<InterviewPlan>(() => clonePlan(initial));
  const [undoStack, setUndoStack] = useState<UndoAction[]>([]);
  // Mirror the undo stack in a ref so undo() can read the current top inverse
  // action synchronously and then call setPlan + setUndoStack as INDEPENDENT
  // top-level setters (no setPlan nested inside the setUndoStack updater, which
  // would run twice under Strict Mode).
  const undoStackRef = useRef<UndoAction[]>([]);
  undoStackRef.current = undoStack;
  // Dirty is a mutation-tracked flag — flipped true the first time the user edits
  // and cleared only by reset(). Avoids the previous JSON.stringify(plan) on every
  // render (O(plan size) each render even when nothing changed).
  const [isDirty, setIsDirty] = useState(false);

  const updateRound = useCallback((roundId: string, patch: Partial<InterviewPlanRound>) => {
    setIsDirty(true);
    setPlan((prev) => {
      const idx = prev.rounds.findIndex((r) => r.id === roundId);
      if (idx === -1) return prev;
      const prior = cloneRound(prev.rounds[idx]!);
      const nextRound = { ...prev.rounds[idx]!, ...patch };
      const nextPlan: InterviewPlan = {
        rounds: prev.rounds.map((r, i) => (i === idx ? nextRound : r)),
      };
      const inverse: UndoAction = () => ({
        rounds: nextPlan.rounds.map((r, i) => (i === idx ? prior : r)),
      });
      setUndoStack((s) => [...s, inverse]);
      return nextPlan;
    });
  }, []);

  const removeRound = useCallback((roundId: string) => {
    setIsDirty(true);
    setPlan((prev) => {
      const idx = prev.rounds.findIndex((r) => r.id === roundId);
      const target = prev.rounds[idx];
      if (idx === -1 || !target) return prev;
      const removed = cloneRound(target);
      const nextPlan: InterviewPlan = {
        rounds: renumber(prev.rounds.filter((_, i) => i !== idx)),
      };
      // Undo re-inserts the removed round at its original index.
      const restore: UndoAction = () => {
        const arr = nextPlan.rounds.map(cloneRound);
        arr.splice(idx, 0, removed);
        return { rounds: renumber(arr) };
      };
      setUndoStack((s) => [...s, restore]);
      return nextPlan;
    });
  }, []);

  const reorderRounds = useCallback((from: number, to: number) => {
    setIsDirty(true);
    setPlan((prev) => {
      if (
        from === to ||
        from < 0 ||
        to < 0 ||
        from >= prev.rounds.length ||
        to >= prev.rounds.length
      ) {
        return prev;
      }
      const priorOrder = prev.rounds.map((r) => r.id);
      const arr = [...prev.rounds];
      const [moved] = arr.splice(from, 1);
      arr.splice(to, 0, moved!);
      const nextPlan: InterviewPlan = { rounds: renumber(arr) };
      const inverse: UndoAction = () => {
        const byId = new Map(prev.rounds.map((r) => [r.id, cloneRound(r)] as const));
        const restored = priorOrder.map((id) => byId.get(id)!);
        return { rounds: renumber(restored) };
      };
      setUndoStack((s) => [...s, inverse]);
      return nextPlan;
    });
  }, []);

  const addGuideline = useCallback((roundId: string, g: Guideline) => {
    setIsDirty(true);
    setPlan((prev) => {
      const idx = prev.rounds.findIndex((r) => r.id === roundId);
      if (idx === -1) return prev;
      const round = prev.rounds[idx]!;
      const nextRound = { ...round, guidelines: [...round.guidelines, { ...g }] };
      const nextPlan: InterviewPlan = {
        rounds: prev.rounds.map((r, i) => (i === idx ? nextRound : r)),
      };
      const inverse: UndoAction = () => ({
        rounds: nextPlan.rounds.map((r, i) =>
          i === idx ? { ...r, guidelines: r.guidelines.slice(0, -1) } : r,
        ),
      });
      setUndoStack((s) => [...s, inverse]);
      return nextPlan;
    });
  }, []);

  const updateGuideline = useCallback(
    (roundId: string, index: number, patch: Partial<Guideline>) => {
      setIsDirty(true);
      setPlan((prev) => {
        const idx = prev.rounds.findIndex((r) => r.id === roundId);
        if (idx === -1) return prev;
        const round = prev.rounds[idx]!;
        if (index < 0 || index >= round.guidelines.length) return prev;
        const prior = { ...round.guidelines[index]! };
        const guidelines = round.guidelines.map((g, i) => (i === index ? { ...g, ...patch } : g));
        const nextRound = { ...round, guidelines };
        const nextPlan: InterviewPlan = {
          rounds: prev.rounds.map((r, i) => (i === idx ? nextRound : r)),
        };
        const inverse: UndoAction = () => ({
          rounds: nextPlan.rounds.map((r, i) =>
            i === idx
              ? { ...r, guidelines: r.guidelines.map((g, j) => (j === index ? prior : g)) }
              : r,
          ),
        });
        setUndoStack((s) => [...s, inverse]);
        return nextPlan;
      });
    },
    [],
  );

  const removeGuideline = useCallback((roundId: string, index: number) => {
    setIsDirty(true);
    setPlan((prev) => {
      const idx = prev.rounds.findIndex((r) => r.id === roundId);
      if (idx === -1) return prev;
      const round = prev.rounds[idx]!;
      if (index < 0 || index >= round.guidelines.length) return prev;
      const removed = { ...round.guidelines[index]! };
      const guidelines = round.guidelines.filter((_, i) => i !== index);
      const nextRound = { ...round, guidelines };
      const nextPlan: InterviewPlan = {
        rounds: prev.rounds.map((r, i) => (i === idx ? nextRound : r)),
      };
      const inverse: UndoAction = () => ({
        rounds: nextPlan.rounds.map((r, i) => {
          if (i !== idx) return r;
          const g = [...r.guidelines];
          g.splice(index, 0, removed);
          return { ...r, guidelines: g };
        }),
      });
      setUndoStack((s) => [...s, inverse]);
      return nextPlan;
    });
  }, []);

  const addFeedbackQuestion = useCallback(
    (roundId: string, q: Omit<FeedbackQuestion, 'id' | 'question_number'>) => {
      setIsDirty(true);
      setPlan((prev) => {
        const idx = prev.rounds.findIndex((r) => r.id === roundId);
        if (idx === -1) return prev;
        const round = prev.rounds[idx]!;
        const newQ: FeedbackQuestion = {
          ...q,
          id: genId('fq'),
          question_number: round.feedback_questions.length + 1,
        };
        const feedback_questions = [...round.feedback_questions, newQ];
        const nextRound = { ...round, feedback_questions };
        const nextPlan: InterviewPlan = {
          rounds: prev.rounds.map((r, i) => (i === idx ? nextRound : r)),
        };
        const inverse: UndoAction = () => ({
          rounds: nextPlan.rounds.map((r, i) =>
            i === idx
              ? { ...r, feedback_questions: r.feedback_questions.filter((f) => f.id !== newQ.id) }
              : r,
          ),
        });
        setUndoStack((s) => [...s, inverse]);
        return nextPlan;
      });
    },
    [],
  );

  const updateFeedbackQuestion = useCallback(
    (roundId: string, questionId: string, patch: Partial<FeedbackQuestion>) => {
      setIsDirty(true);
      setPlan((prev) => {
        const idx = prev.rounds.findIndex((r) => r.id === roundId);
        if (idx === -1) return prev;
        const round = prev.rounds[idx]!;
        const qIdx = round.feedback_questions.findIndex((q) => q.id === questionId);
        if (qIdx === -1) return prev;
        const prior = { ...round.feedback_questions[qIdx]! };
        const feedback_questions = round.feedback_questions.map((q, i) =>
          i === qIdx ? { ...q, ...patch } : q,
        );
        const nextRound = { ...round, feedback_questions };
        const nextPlan: InterviewPlan = {
          rounds: prev.rounds.map((r, i) => (i === idx ? nextRound : r)),
        };
        const inverse: UndoAction = () => ({
          rounds: nextPlan.rounds.map((r, i) =>
            i === idx
              ? {
                  ...r,
                  feedback_questions: r.feedback_questions.map((q, j) => (j === qIdx ? prior : q)),
                }
              : r,
          ),
        });
        setUndoStack((s) => [...s, inverse]);
        return nextPlan;
      });
    },
    [],
  );

  const removeFeedbackQuestion = useCallback((roundId: string, questionId: string) => {
    setIsDirty(true);
    setPlan((prev) => {
      const idx = prev.rounds.findIndex((r) => r.id === roundId);
      if (idx === -1) return prev;
      const round = prev.rounds[idx]!;
      const qIdx = round.feedback_questions.findIndex((q) => q.id === questionId);
      if (qIdx === -1) return prev;
      const removed = { ...round.feedback_questions[qIdx]! };
      const feedback_questions = round.feedback_questions.filter((q) => q.id !== questionId);
      const nextRound = { ...round, feedback_questions };
      const nextPlan: InterviewPlan = {
        rounds: prev.rounds.map((r, i) => (i === idx ? nextRound : r)),
      };
      const inverse: UndoAction = () => ({
        rounds: nextPlan.rounds.map((r, i) => {
          if (i !== idx) return r;
          const list = [...r.feedback_questions];
          list.splice(qIdx, 0, removed);
          return { ...r, feedback_questions: list };
        }),
      });
      setUndoStack((s) => [...s, inverse]);
      return nextPlan;
    });
  }, []);

  // Set (or clear, with `undefined`) the whole per-round screening artifact. The
  // draft screening panel operates on this single object via onChange, so one
  // setter covers generate/derive/toggle/edit (each computes the next screening
  // object and hands it back whole).
  const setRoundScreening = useCallback(
    (roundId: string, screening: RoundScreening | undefined) => {
      setIsDirty(true);
      setPlan((prev) => {
        const idx = prev.rounds.findIndex((r) => r.id === roundId);
        if (idx === -1) return prev;
        const prior = prev.rounds[idx]!.screening;
        const nextRound: InterviewPlanRound = { ...prev.rounds[idx]! };
        if (screening === undefined) {
          delete nextRound.screening;
        } else {
          nextRound.screening = cloneScreening(screening);
        }
        const nextPlan: InterviewPlan = {
          rounds: prev.rounds.map((r, i) => (i === idx ? nextRound : r)),
        };
        const inverse: UndoAction = () => ({
          rounds: nextPlan.rounds.map((r, i) => {
            if (i !== idx) return r;
            const restored: InterviewPlanRound = { ...r };
            if (prior === undefined) {
              delete restored.screening;
            } else {
              restored.screening = cloneScreening(prior);
            }
            return restored;
          }),
        });
        setUndoStack((s) => [...s, inverse]);
        return nextPlan;
      });
    },
    [],
  );

  const undo = useCallback(() => {
    // Read the live stack via the ref, compute the inverse once, then call setPlan
    // and setUndoStack as INDEPENDENT top-level setters. Nesting setPlan inside the
    // setUndoStack updater fires it twice under React Strict Mode (updaters run
    // twice in dev), applying the inverse twice — fragile.
    const stack = undoStackRef.current;
    if (stack.length === 0) return;
    const inverse = stack[stack.length - 1]!;
    setPlan(inverse());
    setUndoStack((s) => s.slice(0, -1));
  }, []);

  const reset = useCallback((next: InterviewPlan) => {
    setPlan(clonePlan(next));
    setUndoStack([]);
    setIsDirty(false);
  }, []);

  const violations = useMemo<PublishViolation[]>(() => {
    const out: PublishViolation[] = [];
    for (const r of plan.rounds) {
      if (!r.name || r.name.trim().length === 0) {
        out.push({ roundId: r.id, kind: 'missing_name' });
      }
      if (r.feedback_questions.length === 0) {
        out.push({ roundId: r.id, kind: 'no_feedback_questions' });
      }
    }
    return out;
  }, [plan]);

  const canPublish = violations.length === 0;

  return {
    plan,
    isDirty,
    canUndo: undoStack.length > 0,
    canPublish,
    violations,
    updateRound,
    removeRound,
    reorderRounds,
    addGuideline,
    updateGuideline,
    removeGuideline,
    addFeedbackQuestion,
    updateFeedbackQuestion,
    removeFeedbackQuestion,
    setRoundScreening,
    undo,
    reset,
  };
}
