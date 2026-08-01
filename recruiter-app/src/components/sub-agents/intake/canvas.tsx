'use client';

import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useIntakeCall } from '@/hooks/intake/use-intake-call';
import { useIntakeSession } from '@/hooks/intake/use-intake-session';
import { useShellSync } from '@/hooks/use-shell-sync';
import { useSubmitIntake } from '@/hooks/intake/use-submit-intake';
import type { PublishResponse } from '@/lib/intake/api';
import { useActiveContextStore } from '@/stores/active-context-store';
import { useComposerStore } from '@/stores/composer-store';
import { useIntakeStore } from '@/stores/intake-store';
import type { IntakeSession, IntakeStage } from '@/types/intake';
import { deriveStage } from './flow';
import { Hub } from './hub/Hub';
import { IntakeSessionProvider } from './IntakeSessionProvider';
import { PlanEditing } from './stages/plan-editing';
import { PlanGenerating } from './stages/plan-generating';
import { PrefillFailedStage } from './stages/prefill-failed';
import { PrefillingStage } from './stages/prefilling';
import { ScorecardFailed } from './stages/scorecard-failed';
import { SessionActiveStage } from './stages/session-active';
import { VoiceReconnectStage } from './stages/voice-reconnect';
import { WrappingStage } from './stages/wrapping';

interface Props {
  id: string;
  sessionId: string | null;
}

// Wraps the canvas tree in ONE shared session subscription. Every descendant
// that calls useIntakeSession(sessionId) for this same id reads from the provider
// instead of opening its own Realtime channel + 1.5s poll (the FE-J5 fan-out fix).
export function IntakeCanvas({ id, sessionId }: Props) {
  return (
    <IntakeSessionProvider sessionId={sessionId}>
      <IntakeCanvasInner id={id} sessionId={sessionId} />
    </IntakeSessionProvider>
  );
}

function IntakeCanvasInner({ id, sessionId }: Props) {
  useShellSync();
  const router = useRouter();
  const { session, isLoading, error } = useIntakeSession(sessionId);
  const call = useIntakeCall();
  const setAgenticScope = useComposerStore((s) => s.setAgenticScope);
  const pendingTransition = useIntakeStore((s) => s.pendingTransition);
  const clearPendingTransition = useIntakeStore((s) => s.clearPendingTransition);
  const hasLiveWebRTC = useIntakeStore((s) => s.hasLiveWebRTC);
  const endedSessionId = useIntakeStore((s) => s.endedSessionId);
  const editPlanSessionId = useIntakeStore((s) => s.editPlanSessionId);
  const setActiveContext = useActiveContextStore((s) => s.setContext);
  const [lastPublishRedirect, setLastPublishRedirect] = useState<string | null>(null);
  // Prevents resume from firing during the async gap after the pause cleanup
  // runs but before this component fully unmounts. Without this, call.pause()
  // triggers a re-render that re-runs the resume effect on the still-mounted
  // canvas, immediately undoing the pause and navigating back into the call.
  const intentionallyPausingRef = useRef(false);
  // The provider's context value is a fresh object on every render, so we read
  // the live `call` through a ref inside the unmount cleanup instead of putting
  // `call` in the effect deps — otherwise the cleanup fires on every render and
  // pauses the active call mid-session (the "Voice paused" + dead-orb bug).
  const callRef = useRef(call);
  callRef.current = call;

  useEffect(() => {
    setAgenticScope('intake');
  }, [setAgenticScope]);

  // Keep intake-store.sessionId in sync so useModalitySwitch (and any other
  // hook that reads from the store) can resolve the active session without
  // prop-drilling.
  const setSessionId = useIntakeStore((s) => s.setSessionId);
  useEffect(() => {
    setSessionId(sessionId);
    return () => setSessionId(null);
  }, [sessionId, setSessionId]);

  // Resume the call when the user re-enters the session route.
  useEffect(() => {
    if (!session || !sessionId) return;
    if (intentionallyPausingRef.current) return;
    if (call.activeSessionId === session.id && call.status === 'paused') {
      void call.resume();
    }
  }, [session, sessionId, call.activeSessionId, call.status, call]);

  // Pause the call ONLY when the user truly leaves this session (sessionId
  // change / canvas unmount) — never on incidental re-renders.
  // biome-ignore lint/correctness/useExhaustiveDependencies: call is read via callRef on purpose; depending on it would pause the live call every render
  useEffect(() => {
    return () => {
      const c = callRef.current;
      // Guard statusRef — the cleanup must never throw during unmount (a throw
      // here corrupts React's commit and cascades into the next render).
      if (c?.statusRef?.current === 'live' && c.activeSessionId === sessionId) {
        intentionallyPausingRef.current = true;
        void c.pause();
      }
    };
  }, [sessionId]);

  useEffect(() => {
    // Clear only when the server has acknowledged the optimistic flip AND the
    // client is in a stable post-handshake state. For voice that means
    // hasLiveWebRTC=true — the voice agent sets active_modality='voice' the
    // moment it receives the SDP offer, well before the WebRTC handshake
    // completes. Clearing on active_modality alone caused deriveStage to flip
    // to 'voice_reconnect' mid-handshake, unmounting VoiceCallPanel and
    // killing the in-flight PeerConnection.
    if (!session || !pendingTransition) return;
    const voiceAcked =
      pendingTransition.to === 'voice_active' &&
      session.active_modality === 'voice' &&
      hasLiveWebRTC;
    const textAcked = pendingTransition.to === 'text_active' && session.active_modality === 'text';
    if (voiceAcked || textAcked) {
      clearPendingTransition();
    }
  }, [
    session?.id,
    session?.updated_at,
    session?.active_modality,
    hasLiveWebRTC,
    pendingTransition,
    clearPendingTransition,
    session,
  ]);

  const onPublished = useCallback(
    (resp: PublishResponse) => {
      if (session) {
        setActiveContext({
          requisitionId: resp.requisition_id,
          roleTitle: session.form_data.role_name,
          source: 'intake',
        });
      }
      setLastPublishRedirect(resp.redirect_url);
      // Go straight to the published role — no in-between "Published" screen.
      router.push(resp.redirect_url);
    },
    [router, setActiveContext, session],
  );

  const onRetried = useCallback(() => {
    // ScorecardFailed re-invokes submit; Realtime + deriveStage flips us back.
  }, []);

  const stage: IntakeStage = deriveStage({
    session,
    pendingTransition,
    hasLiveWebRTC,
    endedSessionId,
    editPlanSessionId,
  });

  // A published session goes straight to its role page — the standalone
  // "Published" confirmation screen is an unnecessary stop. (Editing a published
  // plan is handled by deriveStage returning 'plan_editing', not 'published'.)
  const publishedRedirect =
    stage === 'published' && session
      ? (lastPublishRedirect ?? `/view/roles/${session.requisition_id}`)
      : null;
  useEffect(() => {
    if (publishedRedirect) router.push(publishedRedirect);
  }, [publishedRedirect, router]);

  if (process.env.NODE_ENV !== 'production' && typeof window !== 'undefined') {
  }

  if (error) {
    return (
      <div id={id} className="p-6">
        <div
          id={`${id}-error`}
          role="alert"
          className="rounded border border-red-200 bg-red-50 p-4 text-red-700 text-sm"
        >
          {error.message}
        </div>
      </div>
    );
  }

  if (sessionId && isLoading && !session) {
    return (
      <div id={id} className="p-6">
        <div
          id={`${id}-loading`}
          className="h-32 animate-pulse rounded bg-[var(--surface-accent)]"
        />
      </div>
    );
  }

  return (
    <div id={id}>
      {session && <IntakeAutoSubmit session={session} hasLiveWebRTC={hasLiveWebRTC} />}
      {stage === 'lobby' && <Hub id={`${id}-stage-hub`} />}
      {stage === 'prefilling' && session && (
        <PrefillingStage id={`${id}-stage-prefilling`} session={session} />
      )}
      {stage === 'prefill_failed' && (
        <PrefillFailedStage
          id={`${id}-stage-prefill-failed`}
          onContinue={() => router.push('/intake')}
        />
      )}
      {(stage === 'voice_active' || stage === 'text_active') && session && (
        <SessionActiveStage session={session} mode={stage === 'voice_active' ? 'voice' : 'text'} />
      )}
      {stage === 'voice_reconnect' && session && <VoiceReconnectStage session={session} />}
      {stage === 'wrapping' && session && <WrappingStage session={session} />}
      {stage === 'plan_generating' && session && <PlanGenerating session={session} />}
      {stage === 'plan_editing' && session && (
        <PlanEditing session={session} onPublished={onPublished} />
      )}
      {stage === 'scorecard_failed' && session && (
        <ScorecardFailed session={session} onRetried={onRetried} />
      )}
      {stage === 'published' && session && (
        <div
          id={`${id}-stage-published-redirect`}
          className="h-32 animate-pulse rounded bg-[var(--surface-accent)]"
        />
      )}
    </div>
  );
}

// Renders nothing — its only job is to own the auto-submit effect via the shared
// useSubmitIntake hook (single in-flight guard + stable-primitive deps). Mounting
// it only when a session exists keeps the hook unconditional inside the component
// while letting the canvas gate on session presence.
function IntakeAutoSubmit({
  session,
  hasLiveWebRTC,
}: {
  session: IntakeSession;
  hasLiveWebRTC: boolean;
}) {
  useSubmitIntake(session, { auto: true, hasLiveWebRTC });
  return null;
}
