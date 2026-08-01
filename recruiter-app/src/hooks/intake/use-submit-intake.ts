'use client';

import { useCallback, useEffect, useState } from 'react';
import { IntakeApiError, submitSession } from '@/lib/intake/api';
import { useIntakeStore } from '@/stores/intake-store';
import type { IntakeSession } from '@/types/intake';

interface SubmitOptions {
  // When true, the hook auto-submits once the session is submittable, every goal
  // is resolved, a real conversation happened, and no live call is in progress.
  auto?: boolean;
  // The canvas owns the live-WebRTC signal; pass it so we never cut off a call.
  hasLiveWebRTC?: boolean;
}

// A goal is resolved once it's been addressed — captured, confirmed, OR explicitly
// skipped. Only 'untouched' / 'needs_probe' are still open.
function allGoalsResolved(session: IntakeSession): boolean {
  const questions = session.questions_snapshot ?? [];
  if (questions.length === 0) return false;
  const answers = session.current_answers ?? {};
  return questions.every((q) => {
    const st = answers[q.id]?.status ?? 'untouched';
    return st === 'validated' || st === 'discussed' || st === 'skipped';
  });
}

// Shared "Submit intake" controller. ONE place owns the submit call + the single
// in-flight guard (store.submitInFlightFor), so the auto-submit path and the
// Wrapping-stage button can never double-fire one submit. The auto-submit effect
// depends on STABLE PRIMITIVES (id, status, resolved-flag, turn count, live flag)
// — not the whole session object — so a realtime tick that only bumps updated_at
// never re-evaluates it.
export function useSubmitIntake(session: IntakeSession, options: SubmitOptions = {}) {
  const { auto = false, hasLiveWebRTC = false } = options;
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const setPendingTransition = useIntakeStore((s) => s.setPendingTransition);
  const clearPendingTransition = useIntakeStore((s) => s.clearPendingTransition);
  const setSubmittingError = useIntakeStore((s) => s.setSubmittingError);
  const submittingError = useIntakeStore((s) => s.submittingError);

  const submit = useCallback(async (): Promise<void> => {
    const { beginSubmit, endSubmit } = useIntakeStore.getState();
    // Deterministic single guard across ALL submit paths + instances.
    if (!beginSubmit(session.id)) return;
    setSubmittingError(null);
    setSubmitting(true);
    setPendingTransition('plan_generating', 8_000);
    try {
      await submitSession(session.id);
      setConfirmOpen(false);
    } catch (e) {
      clearPendingTransition();
      setSubmittingError(e instanceof IntakeApiError ? e.detail : 'Submit failed. Try again.');
    } finally {
      setSubmitting(false);
      endSubmit(session.id);
    }
  }, [session.id, setPendingTransition, clearPendingTransition, setSubmittingError]);

  // Stable primitives — recompute auto-submit eligibility ONLY when one of these
  // changes, not on every realtime push of a fresh session object. (session.id is
  // covered transitively: `submit` is keyed on it, so a new session re-runs this.)
  const status = session.status;
  const submittable = status === 'ready' || status === 'active';
  const resolved = allGoalsResolved(session);
  const hasTurns = (session.turns?.length ?? 0) > 0;
  // A failed submit rolls status back to 'ready', which re-satisfies the
  // auto-submit condition. Without this guard the failed→ready→auto-resubmit
  // cycle becomes an infinite plan-regeneration loop. After a failure the user
  // retries explicitly (ScorecardFailed's Retry / the Wrapping submit button).
  const processFailed = session.process_status === 'failed';

  useEffect(() => {
    if (!auto) return;
    if (!submittable || !resolved || !hasTurns || hasLiveWebRTC) return;
    if (processFailed) return;
    void submit();
  }, [auto, submittable, resolved, hasTurns, hasLiveWebRTC, processFailed, submit]);

  return { confirmOpen, setConfirmOpen, submitting, submittingError, submit };
}
