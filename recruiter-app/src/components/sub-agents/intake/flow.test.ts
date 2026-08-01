import { describe, expect, test } from 'bun:test';
import type { IntakeSession } from '@/types/intake';
import { deriveStage } from './flow';

function s(over: Partial<IntakeSession> = {}): IntakeSession {
  return {
    id: 'x',
    requisition_id: 'r',
    user_id: 'u',
    organization_id: 'o',
    status: 'created',
    active_modality: null,
    entry_point: null,
    form_data: {
      role_name: 'r',
      experience_min: 0,
      experience_max: 5,
      location: 'NYC',
      jd_text: null,
    },
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
    ...over,
  };
}

describe('deriveStage', () => {
  test('no session → lobby (the Hub)', () => {
    expect(deriveStage({ session: null, pendingTransition: null, hasLiveWebRTC: false })).toBe(
      'lobby',
    );
  });
  test('status=created → prefilling', () => {
    expect(
      deriveStage({
        session: s({ status: 'created' }),
        pendingTransition: null,
        hasLiveWebRTC: false,
      }),
    ).toBe('prefilling');
  });
  test('status=prefilling → prefilling', () => {
    expect(
      deriveStage({
        session: s({ status: 'prefilling' }),
        pendingTransition: null,
        hasLiveWebRTC: false,
      }),
    ).toBe('prefilling');
  });
  test('status=ready + no modality + no turns → voice_active (voice-first auto-start)', () => {
    expect(
      deriveStage({
        session: s({ status: 'ready' }),
        pendingTransition: null,
        hasLiveWebRTC: false,
      }),
    ).toBe('voice_active');
  });
  test('failed in the prefill phase (created/prefilling, no plan) → prefill_failed', () => {
    expect(
      deriveStage({
        session: s({ status: 'prefilling', process_status: 'failed' }),
        pendingTransition: null,
        hasLiveWebRTC: false,
      }),
    ).toBe('prefill_failed');
    expect(
      deriveStage({
        session: s({ status: 'created', process_status: 'failed' }),
        pendingTransition: null,
        hasLiveWebRTC: false,
      }),
    ).toBe('prefill_failed');
  });
  test('process_status=failed AND status=submitted → scorecard_failed', () => {
    expect(
      deriveStage({
        session: s({ status: 'submitted', process_status: 'failed' }),
        pendingTransition: null,
        hasLiveWebRTC: false,
      }),
    ).toBe('scorecard_failed');
  });
  // A submit/regenerate failure rolls the session back to 'ready' (intake_submit_service
  // / the v2 Lambda's mark_session_failed). The conversation + any plan are intact, so
  // this is a RETRY situation — never the "couldn't prefill, start fresh" dead-end.
  test('failed after the conversation (status=ready, plan present) → scorecard_failed, NOT prefill_failed', () => {
    expect(
      deriveStage({
        session: s({
          status: 'ready',
          process_status: 'failed',
          interview_plan: { rounds: [] },
          turns: [{ idx: 0, role: 'user', content: 'hi', modality: 'text', timestamp: 'x' }],
        }),
        pendingTransition: null,
        hasLiveWebRTC: false,
      }),
    ).toBe('scorecard_failed');
  });
  test('failed at status=ready with a real conversation but no plan yet → scorecard_failed', () => {
    expect(
      deriveStage({
        session: s({
          status: 'ready',
          process_status: 'failed',
          turns: [{ idx: 0, role: 'user', content: 'hi', modality: 'text', timestamp: 'x' }],
        }),
        pendingTransition: null,
        hasLiveWebRTC: false,
      }),
    ).toBe('scorecard_failed');
  });
  test('status=published → published', () => {
    expect(
      deriveStage({
        session: s({ status: 'published' }),
        pendingTransition: null,
        hasLiveWebRTC: false,
      }),
    ).toBe('published');
  });
  test('published + editPlanSessionId match + plan present → plan_editing (Hub edit-existing)', () => {
    expect(
      deriveStage({
        session: s({ status: 'published', interview_plan: { rounds: [] } }),
        pendingTransition: null,
        hasLiveWebRTC: false,
        editPlanSessionId: 'x',
      }),
    ).toBe('plan_editing');
  });
  test('status=submitted + interview_plan present → plan_editing', () => {
    expect(
      deriveStage({
        session: s({ status: 'submitted', interview_plan: { rounds: [] } }),
        pendingTransition: null,
        hasLiveWebRTC: false,
      }),
    ).toBe('plan_editing');
  });
  test('status=submitted + interview_plan null → plan_generating', () => {
    expect(
      deriveStage({
        session: s({ status: 'submitted' }),
        pendingTransition: null,
        hasLiveWebRTC: false,
      }),
    ).toBe('plan_generating');
  });
  test('active_modality=voice + hasLiveWebRTC=true → voice_active', () => {
    expect(
      deriveStage({
        session: s({ status: 'active', active_modality: 'voice' }),
        pendingTransition: null,
        hasLiveWebRTC: true,
      }),
    ).toBe('voice_active');
  });
  test('active_modality=voice + no WebRTC + no turns → voice_active (initial connection)', () => {
    // Voice agent sets active_modality='voice' on receiving the SDP offer,
    // before the WebRTC handshake completes. Stay on voice_active so the
    // panel keeps mounted while the call comes up.
    expect(
      deriveStage({
        session: s({ status: 'active', active_modality: 'voice' }),
        pendingTransition: null,
        hasLiveWebRTC: false,
      }),
    ).toBe('voice_active');
  });
  test('active_modality=voice + no WebRTC + turns present → voice_active (auto-reconnect, no rejoin modal)', () => {
    expect(
      deriveStage({
        session: s({
          status: 'active',
          active_modality: 'voice',
          turns: [{ idx: 0, role: 'assistant', content: 'hi', modality: 'voice', timestamp: 'x' }],
        }),
        pendingTransition: null,
        hasLiveWebRTC: false,
      }),
    ).toBe('voice_active');
  });
  test('active_modality=text → text_active', () => {
    expect(
      deriveStage({
        session: s({ status: 'active', active_modality: 'text' }),
        pendingTransition: null,
        hasLiveWebRTC: false,
      }),
    ).toBe('text_active');
  });
  test('no modality + turns>0 + NOT explicitly ended → resume conversation (last modality), NOT wrapping', () => {
    // Regression: the lock going null mid-intake (stale-lock cleanup, drain,
    // refetch gap) must never auto-jump to the submit screen.
    expect(
      deriveStage({
        session: s({
          status: 'active',
          turns: [{ idx: 0, role: 'assistant', content: 'hi', modality: 'voice', timestamp: 'x' }],
        }),
        pendingTransition: null,
        hasLiveWebRTC: false,
      }),
    ).toBe('voice_active');
    expect(
      deriveStage({
        session: s({
          status: 'active',
          turns: [{ idx: 0, role: 'user', content: 'hi', modality: 'text', timestamp: 'x' }],
        }),
        pendingTransition: null,
        hasLiveWebRTC: false,
      }),
    ).toBe('text_active');
  });
  test('no modality + turns>0 + endedSessionId matches → wrapping (explicit end only)', () => {
    expect(
      deriveStage({
        session: s({
          id: 'sess-1',
          status: 'active',
          turns: [{ idx: 0, role: 'user', content: 'hi', modality: 'text', timestamp: 'x' }],
        }),
        pendingTransition: null,
        hasLiveWebRTC: false,
        endedSessionId: 'sess-1',
      }),
    ).toBe('wrapping');
  });
  test('endedSessionId for a DIFFERENT session does not force wrapping', () => {
    expect(
      deriveStage({
        session: s({
          id: 'sess-1',
          status: 'active',
          turns: [{ idx: 0, role: 'user', content: 'hi', modality: 'text', timestamp: 'x' }],
        }),
        pendingTransition: null,
        hasLiveWebRTC: false,
        endedSessionId: 'sess-OTHER',
      }),
    ).toBe('text_active');
  });
  test('unexpired pendingTransition overrides row-derived stage', () => {
    expect(
      deriveStage({
        session: s({ status: 'created' }),
        pendingTransition: { to: 'ready_choose_modality', expiresAt: Date.now() + 5000 },
        hasLiveWebRTC: false,
      }),
    ).toBe('ready_choose_modality');
  });
  test('expired pendingTransition is ignored', () => {
    expect(
      deriveStage({
        session: s({ status: 'created' }),
        pendingTransition: { to: 'ready_choose_modality', expiresAt: Date.now() - 1 },
        hasLiveWebRTC: false,
      }),
    ).toBe('prefilling');
  });
  test('published wins outright when status=published', () => {
    expect(
      deriveStage({
        session: s({ status: 'published', process_status: 'failed' }),
        pendingTransition: null,
        hasLiveWebRTC: false,
      }),
    ).toBe('published');
  });
});

describe('deriveStage Phase 2 voice branches', () => {
  test('pendingTransition voice_active wins over row-derived stage', () => {
    expect(
      deriveStage({
        session: s({ status: 'created' }),
        pendingTransition: { to: 'voice_active', expiresAt: Date.now() + 5000 },
        hasLiveWebRTC: false,
      }),
    ).toBe('voice_active');
  });
  test('a failure during an active voice session → scorecard_failed (retry), not prefill_failed', () => {
    expect(
      deriveStage({
        session: s({ status: 'active', active_modality: 'voice', process_status: 'failed' }),
        pendingTransition: null,
        hasLiveWebRTC: true,
      }),
    ).toBe('scorecard_failed');
  });

  // A clean voice [END] flips the row to status='ready' (voice agent
  // _end_session("conversation_complete")); a drop leaves it 'active'. Once the call
  // is fully down, a clean completion advances to the submit (wrapping) screen
  // instead of re-opening on "Voice paused / Start call".
  const voiceTurn = { idx: 0, role: 'assistant' as const, content: 'bye', modality: 'voice' as const, timestamp: 'x' };
  test('clean voice end (status=ready, voice turns, call down) → wrapping (submit screen)', () => {
    expect(
      deriveStage({
        session: s({ status: 'ready', active_modality: null, turns: [voiceTurn] }),
        pendingTransition: null,
        hasLiveWebRTC: false,
      }),
    ).toBe('wrapping');
  });
  test('status=ready with a live call (mid-call lock gap) → voice_active, NOT wrapping', () => {
    expect(
      deriveStage({
        session: s({ status: 'ready', active_modality: null, turns: [voiceTurn] }),
        pendingTransition: null,
        hasLiveWebRTC: true,
      }),
    ).toBe('voice_active');
  });
  test('accidental drop (status stays active, no [END]) → resume voice_active, NOT wrapping', () => {
    expect(
      deriveStage({
        session: s({ status: 'active', active_modality: null, turns: [voiceTurn] }),
        pendingTransition: null,
        hasLiveWebRTC: false,
      }),
    ).toBe('voice_active');
  });
});
