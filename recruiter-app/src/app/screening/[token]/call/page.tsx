'use client';

import {
  AlertCircle,
  Clock,
  Loader2,
  MessageSquareText,
  Mic,
  MicOff,
  PhoneOff,
} from 'lucide-react';
import { useParams, useRouter } from 'next/navigation';
import { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { FeedbackTranscriptPane } from '@/components/feedback/feedback-transcript-pane';
import { BrandIcon } from '@/components/icons/brand-icons';
import {
  ScreeningCallProvider,
  useScreeningCall,
} from '@/components/screening/screening-call-provider';
import { Button } from '@/components/ui/button';
import { useScreeningSession } from '@/hooks/use-screening-session';
import { cn } from '@/lib/utils';
import { getContext, type ScreeningContext, startVoice } from '@/services/public-screening';

// Candidate-facing screening call. No scorecard, no review/edit, no processing
// poll — that's all recruiter-side. The candidate flow is: pre-call ("what to
// expect") → voice conversation with the agent → "thanks, we'll be in touch".
type Phase = 'loading' | 'precall' | 'calling' | 'ended' | 'error';

// Approximate duration we tell candidates to expect, in minutes.
const EXPECTED_MINUTES = 10;

function VoiceCallView({ onEnd }: { onEnd: () => void }) {
  const call = useScreeningCall();
  const connecting = call.status === 'connecting';
  const live = call.status === 'live';
  const [showTranscript, setShowTranscript] = useState(false);

  return (
    <div id="screening-call-view" className="flex flex-col items-center gap-8 py-10">
      <div
        id="screening-call-orb"
        className={cn(
          'relative flex h-40 w-40 items-center justify-center rounded-full',
          'bg-[radial-gradient(circle_at_center,var(--cortex-orb,theme(colors.indigo.400))_0%,transparent_70%)]',
          live && 'animate-pulse',
        )}
      >
        <BrandIcon id="screening-call-orb-icon" className="h-10 w-10 text-charcoal" />
      </div>

      <p id="screening-call-status" className="text-[13px] text-text-secondary">
        {connecting
          ? 'Connecting…'
          : live
            ? 'Listening — answer OpenRecruiting out loud, like a normal conversation.'
            : 'Wrapping up…'}
      </p>

      {call.lastError && (
        <p id="screening-call-error" className="max-w-sm text-center text-[12px] text-red-600">
          {call.lastError}
        </p>
      )}

      <div id="screening-call-controls" className="flex items-center gap-3">
        <Button
          id="screening-call-mute"
          variant="secondary"
          icon={call.isMuted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
          onClick={() => call.toggleMute()}
          disabled={!live}
        >
          {call.isMuted ? 'Unmute' : 'Mute'}
        </Button>
        <Button
          id="screening-call-transcript"
          variant="secondary"
          icon={<MessageSquareText className="h-4 w-4" />}
          onClick={() => setShowTranscript((v) => !v)}
          aria-pressed={showTranscript}
        >
          Transcript
        </Button>
        <Button
          id="screening-call-end"
          variant="destructive"
          icon={<PhoneOff className="h-4 w-4" />}
          onClick={onEnd}
        >
          End interview
        </Button>
      </div>

      <FeedbackTranscriptPane
        id="screening-transcript-pane"
        open={showTranscript}
        turns={call.transcript}
        interim={call.botInterim}
        onClose={() => setShowTranscript(false)}
      />
    </div>
  );
}

function ScreeningCallInner() {
  const router = useRouter();
  const params = useParams<{ token: string }>();
  const token = params.token;
  const { sessionToken, ready } = useScreeningSession(token);
  const call = useScreeningCall();

  const [phase, setPhase] = useState<Phase>('loading');
  const [ctx, setCtx] = useState<ScreeningContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const prevCallStatus = useRef(call.status);

  // --- initial load --------------------------------------------------------
  // biome-ignore lint/correctness/useExhaustiveDependencies: one-shot load once session is ready; router is stable and intentionally excluded
  useEffect(() => {
    if (!ready) return;
    // The screening session is the gate. Without it, there is nothing to call
    // with — bounce back to the OTP verify page (matches the feedback flow).
    if (!sessionToken) {
      router.replace(`/screening/${token}/verify`);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const context = await getContext(token);
        if (cancelled) return;
        setCtx(context);
        setPhase('precall');
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : 'Could not load this screening session.');
        setPhase('error');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, sessionToken, token]);

  // --- voice call lifecycle: live -> ended transitions into the thanks screen
  useEffect(() => {
    const prev = prevCallStatus.current;
    prevCallStatus.current = call.status;
    if (
      phase === 'calling' &&
      call.status === 'ended' &&
      (prev === 'live' || prev === 'connecting')
    ) {
      if (call.lastError) {
        setError(call.lastError);
        setPhase('error');
      } else {
        setPhase('ended');
      }
    }
  }, [call.status, call.lastError, phase]);

  const startCall = useCallback(async () => {
    if (!sessionToken) return;
    setError(null);
    setPhase('calling');
    try {
      const { voice_session_token } = await startVoice(token, sessionToken);
      await call.start(voice_session_token);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start the screening interview.');
      setPhase('error');
    }
  }, [token, sessionToken, call]);

  const endCall = useCallback(async () => {
    await call.end();
    setPhase('ended');
  }, [call]);

  // --- render --------------------------------------------------------------
  if (phase === 'loading') {
    return (
      <Centered>
        <Loader2 id="screening-call-loading" className="h-5 w-5 animate-spin text-text-secondary" />
      </Centered>
    );
  }

  if (phase === 'error') {
    return (
      <Centered>
        <div
          id="screening-call-error-view"
          className="flex max-w-sm flex-col items-center gap-4 text-center"
        >
          <AlertCircle id="screening-call-error-icon" className="h-6 w-6 text-red-600" />
          <p id="screening-call-error-message" className="text-[13px] text-text-secondary">
            {error}
          </p>
          <Button id="screening-call-error-retry" variant="secondary" onClick={() => startCall()}>
            Try again
          </Button>
        </div>
      </Centered>
    );
  }

  if (phase === 'ended') {
    return (
      <Centered>
        <div
          id="screening-call-ended-view"
          className="flex max-w-sm flex-col items-center gap-3 text-center"
        >
          <BrandIcon id="screening-call-ended-icon" className="h-8 w-8 text-charcoal" />
          <h1 id="screening-call-ended-title" className="font-semibold text-charcoal text-lg">
            Thanks for your time
          </h1>
          <p id="screening-call-ended-message" className="text-[13px] text-text-secondary">
            Your interview is complete. The recruiting team will review it and be in touch with next
            steps. You can safely close this window.
          </p>
        </div>
      </Centered>
    );
  }

  if (phase === 'calling') {
    return (
      <Centered>
        <VoiceCallView onEnd={endCall} />
      </Centered>
    );
  }

  // precall — "what to expect" + Start.
  return (
    <Centered>
      <div
        id="screening-precall-view"
        className="flex max-w-sm flex-col items-center gap-5 text-center"
      >
        <BrandIcon id="screening-precall-icon" className="h-8 w-8 text-charcoal" />
        <div id="screening-precall-heading" className="flex flex-col gap-1">
          <h1 id="screening-precall-title" className="font-semibold text-charcoal text-lg">
            Your screening interview
          </h1>
          {ctx?.role_title && (
            <p id="screening-precall-subtitle" className="text-[13px] text-text-secondary">
              {ctx.role_title}
              {ctx.round_name ? ` · ${ctx.round_name}` : ''}
            </p>
          )}
        </div>
        <p id="screening-precall-intro" className="text-[13px] text-text-secondary">
          You'll have a short voice conversation with OpenRecruiting, our interview assistant — about{' '}
          {EXPECTED_MINUTES} minutes. Speak naturally; there are no trick questions.
        </p>
        <ul
          id="screening-precall-tips"
          className="flex flex-col gap-2 text-left text-[13px] text-text-secondary"
        >
          <li id="screening-precall-tip-quiet" className="flex items-start gap-2">
            <Clock className="mt-0.5 h-4 w-4 shrink-0 text-text-tertiary" />
            Find a quiet spot where you can talk uninterrupted.
          </li>
          <li id="screening-precall-tip-mic" className="flex items-start gap-2">
            <Mic className="mt-0.5 h-4 w-4 shrink-0 text-text-tertiary" />
            When you start, your browser will ask to use your microphone — please allow it.
          </li>
        </ul>
        <Button id="screening-start-call" size="lg" onClick={() => startCall()}>
          Start interview
        </Button>
      </div>
    </Centered>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <main
      id="screening-call-main"
      className="flex min-h-dvh items-center justify-center bg-canvas px-4"
    >
      {children}
    </main>
  );
}

export default function ScreeningCallPage() {
  return (
    <Suspense
      fallback={
        <main
          id="screening-call-suspense"
          className="flex min-h-dvh items-center justify-center bg-canvas"
        >
          <Loader2 className="h-5 w-5 animate-spin text-text-secondary" />
        </main>
      }
    >
      <ScreeningCallProvider>
        <ScreeningCallInner />
      </ScreeningCallProvider>
    </Suspense>
  );
}
