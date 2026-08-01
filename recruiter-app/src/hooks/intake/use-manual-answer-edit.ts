'use client';

import { useCallback, useState } from 'react';
import { flushSync } from 'react-dom';
import { patchAnswers, type PatchAnswerEntry, IntakeApiError } from '@/lib/intake/api';
import type { QuestionId } from '@/types/intake';

interface UseManualAnswerEditResult {
  savingQid: QuestionId | null;
  error: string | null;
  saveEdit: (qid: QuestionId, patch: PatchAnswerEntry) => Promise<{ applied: QuestionId[] } | null>;
  clearError: () => void;
}

export function useManualAnswerEdit(sessionId: string | null): UseManualAnswerEditResult {
  const [savingQid, setSavingQid] = useState<QuestionId | null>(null);
  const [error, setError] = useState<string | null>(null);

  const clearError = useCallback(() => setError(null), []);

  const saveEdit = useCallback(async (qid: QuestionId, patch: PatchAnswerEntry) => {
    if (!sessionId) {
      setError('no session id — refresh the page');
      return null;
    }
    flushSync(() => {
      setSavingQid(qid);
      setError(null);
    });
    try {
      const res = await patchAnswers(sessionId, { [qid]: patch } as Partial<Record<QuestionId, PatchAnswerEntry>>);
      return res;
    } catch (err: unknown) {
      if (err instanceof IntakeApiError) setError(err.detail);
      else setError(err instanceof Error ? err.message : 'edit failed');
      return null;
    } finally {
      setSavingQid(null);
    }
  }, [sessionId]);

  return { savingQid, error, saveEdit, clearError };
}
