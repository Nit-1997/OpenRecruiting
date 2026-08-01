// Pure function: derives the active stage from server state + minimal client
// signals. The single source of truth for stage transitions per spec §6.2.
// Components never compute their own stage — they read the result.

import type { IntakeSession, IntakeStage } from '@/types/intake';

export interface StageDeriveContext {
  session: IntakeSession | null;
  pendingTransition: { to: IntakeStage; expiresAt: number } | null;
  /** True when the WebRTC connection is live in this tab. Phase 1: always false. */
  hasLiveWebRTC: boolean;
  /**
   * Session id the user has *explicitly* ended (clicked "End chat"). Only this
   * signal moves an in-progress conversation to the `wrapping`/submit screen —
   * NOT the absence of a modality lock, which goes null routinely (stale-lock
   * cleanup, modality-switch drain, realtime refetch gaps).
   */
  endedSessionId?: string | null;
  /**
   * Session id the user opened from the Hub's "Edit existing" list. A published
   * session normally derives to `published` (the live, link-out screen); this
   * overrides that to `plan_editing` so the recruiter can refine + re-publish.
   */
  editPlanSessionId?: string | null;
}

/** The last turn that carries a modality, used to resume the right stage. */
function lastTurnModality(session: IntakeSession): 'voice' | 'text' | null {
  const turns = session.turns ?? [];
  for (let i = turns.length - 1; i >= 0; i--) {
    const m = turns[i]?.modality;
    if (m === 'voice' || m === 'text') return m;
  }
  return null;
}

export function deriveStage(ctx: StageDeriveContext): IntakeStage {
  if (ctx.pendingTransition && Date.now() < ctx.pendingTransition.expiresAt) {
    return ctx.pendingTransition.to;
  }

  const s = ctx.session;
  if (!s) return 'lobby';

  if (s.status === 'published') {
    // "Edit existing" reopens the plan editor on a published role; otherwise
    // show the live requisition screen (which links out to the dashboard).
    return ctx.editPlanSessionId === s.id && s.interview_plan ? 'plan_editing' : 'published';
  }

  if (s.process_status === 'failed') {
    // 'prefill_failed' ("couldn't prefill — start fresh") is ONLY truthful in the
    // early prefill phase: still created/prefilling with nothing built yet. Any
    // later failure is a submit/regenerate/scorecard Lambda that rolled the session
    // back to 'ready'/'active' (or left it 'submitted') — the conversation and any
    // generated plan are intact, so it is retry-able. Route it to the retry screen,
    // never the prefill dead-end (which strands the recruiter on a finished plan and
    // its "start fresh" copy implies the plan is lost). ScorecardFailed's Retry
    // re-invokes submit, which the backend accepts from status ready|active.
    const inPrefillPhase =
      (s.status === 'created' || s.status === 'prefilling') && !s.interview_plan;
    return inPrefillPhase ? 'prefill_failed' : 'scorecard_failed';
  }

  if (s.status === 'submitted') {
    return s.interview_plan ? 'plan_editing' : 'plan_generating';
  }

  if (s.status === 'created' || s.status === 'prefilling') return 'prefilling';

  // Voice is always the auto-connecting stage. VoiceCallPanel mounts and the
  // pipecat client (re)connects on its own — exactly like recruiter-app v1 — so
  // switching to / resuming voice "just starts talking". No manual rejoin gate
  // (that modal fired spuriously on every switch, since text turns already
  // exist). A genuine drop is handled by the client's own reconnect; a hard
  // failure trips voiceError → the voice→text fallback.
  if (s.active_modality === 'voice') return 'voice_active';
  if (s.active_modality === 'text') return 'text_active';

  // active_modality is null below. This is NOT a completion signal — the lock is
  // released routinely (stale-lock cleanup after idle, voice→text drain, refetch
  // gaps). Only an explicit end (endedSessionId) moves to the submit screen.
  //
  // Voice-first: a freshly-ready session (no turns yet) opens directly into the
  // voice call — VoiceCallPanel auto-connects pipecat and, on mic-deny, trips
  // voiceError → the in-call fallback to text. There is no separate
  // "voice or chat?" choice screen.
  if ((s.turns?.length ?? 0) === 0) return 'voice_active';
  if (ctx.endedSessionId && ctx.endedSessionId === s.id) return 'wrapping';
  // A clean voice [END] flips the row to status='ready' (the voice agent's
  // _end_session("conversation_complete")); an accidental drop leaves it 'active'.
  // Once the WebRTC call is fully torn down (!hasLiveWebRTC), treat a clean
  // completion as the agent finishing the intake → advance to the submit screen,
  // instead of re-opening on "Voice paused / Start call". The !hasLiveWebRTC guard
  // stops a mid-call active_modality refetch-gap (status can read 'ready' while the
  // call is still live) from yanking the recruiter to submit.
  if (s.status === 'ready' && !ctx.hasLiveWebRTC && lastTurnModality(s) === 'voice') {
    return 'wrapping';
  }
  // Conversation in progress but the lock lapsed — resume where we left off
  // instead of dumping the user onto the submit screen mid-intake.
  return lastTurnModality(s) === 'voice' ? 'voice_active' : 'text_active';
}
