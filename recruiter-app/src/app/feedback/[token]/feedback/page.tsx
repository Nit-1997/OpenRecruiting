'use client';

import { AlertCircle, Loader2, MessageSquareText, Mic, MicOff, PhoneOff } from 'lucide-react';
import { useParams, useRouter } from 'next/navigation';
import { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import {
  FeedbackCallProvider,
  useFeedbackCall,
} from '@/components/feedback/feedback-call-provider';
import { FeedbackEdit } from '@/components/feedback/feedback-edit';
import { FeedbackTranscriptPane } from '@/components/feedback/feedback-transcript-pane';
import { BrandIcon } from '@/components/icons/brand-icons';
import { Button } from '@/components/ui/button';
import { useFeedbackSession } from '@/hooks/use-feedback-session';
import { cn } from '@/lib/utils';
import {
  type FeedbackReview,
  type FeedbackSession,
  getReview,
  getSession,
  startVoice,
} from '@/services/public-feedback';

type Phase =
  | 'loading'
  | 'intro'
  | 'calling'
  | 'submitted'
  | 'processing'
  | 'edit'
  | 'done'
  | 'error';

const POLL_MS = 3000;

function isProcessing(r: FeedbackReview | null): boolean {
  return !!r && (r.processing_status === 'processing' || r.processing_status === 'pending');
}

function isReadyToEdit(r: FeedbackReview | null): boolean {
  return (
    !!r &&
    !isProcessing(r) &&
    r.feedback_voice_session_status !== 'in_progress' &&
    (!!r.summary || !!r.rating)
  );
}

function VoiceCallView({ onEnd }: { onEnd: () => void }) {
  const call = useFeedbackCall();
  const connecting = call.status === 'connecting';
  const live = call.status === 'live';
  const [showTranscript, setShowTranscript] = useState(false);

  return (
    <div className="flex flex-col items-center gap-8 py-10">
      <div
        className={cn(
          'relative flex h-40 w-40 items-center justify-center rounded-full',
          'bg-[radial-gradient(circle_at_center,var(--cortex-orb,theme(colors.indigo.400))_0%,transparent_70%)]',
          live && 'animate-pulse',
        )}
      >
        <BrandIcon className="h-10 w-10 text-charcoal" />
      </div>

      <p className="text-[13px] text-text-secondary">
        {connecting
          ? 'Connecting…'
          : live
            ? 'Listening — talk through your feedback with OpenRecruiting.'
            : 'Wrapping up…'}
      </p>

      <div className="flex items-center gap-3">
        <Button
          id="feedback-call-mute"
          variant="secondary"
          icon={call.isMuted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
          onClick={() => call.toggleMute()}
          disabled={!live}
        >
          {call.isMuted ? 'Unmute' : 'Mute'}
        </Button>
        <Button
          id="feedback-call-transcript"
          variant="secondary"
          icon={<MessageSquareText className="h-4 w-4" />}
          onClick={() => setShowTranscript((v) => !v)}
          aria-pressed={showTranscript}
        >
          Transcript
        </Button>
        <Button
          id="feedback-call-end"
          variant="destructive"
          icon={<PhoneOff className="h-4 w-4" />}
          onClick={onEnd}
        >
          End call
        </Button>
      </div>

      <FeedbackTranscriptPane
        open={showTranscript}
        turns={call.transcript}
        interim={call.botInterim}
        onClose={() => setShowTranscript(false)}
      />
    </div>
  );
}

function FeedbackInner() {
  const router = useRouter();
  const params = useParams<{ token: string }>();
  const token = params.token;
  const { sessionToken, ready } = useFeedbackSession(token);
  const call = useFeedbackCall();

  const [phase, setPhase] = useState<Phase>('loading');
  const [session, setSession] = useState<FeedbackSession | null>(null);
  const [review, setReview] = useState<FeedbackReview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const prevCallStatus = useRef(call.status);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const beginPolling = useCallback(() => {
    if (!sessionToken) return;
    stopPolling();
    setPhase('processing');
    pollRef.current = setInterval(async () => {
      try {
        const r = await getReview(token, sessionToken);
        if (r.processing_status === 'failed' || r.feedback_voice_session_status === 'error') {
          stopPolling();
          setError(
            r.feedback_voice_session_error ??
              'We could not process the feedback. Please try recording again.',
          );
          setPhase('error');
          return;
        }
        if (isReadyToEdit(r)) {
          stopPolling();
          setReview(r);
          setPhase('edit');
        }
      } catch {
        /* transient — keep polling */
      }
    }, POLL_MS);
  }, [token, sessionToken, stopPolling]);

  // --- initial load --------------------------------------------------------
  // biome-ignore lint/correctness/useExhaustiveDependencies: one-shot load once session is ready; beginPolling/router are stable and intentionally excluded
  useEffect(() => {
    if (!ready) return;
    if (!sessionToken) {
      router.replace(`/feedback/${token}/verify`);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const [s, r] = await Promise.all([
          getSession(token, sessionToken),
          getReview(token, sessionToken).catch(() => null),
        ]);
        if (cancelled) return;
        setSession(s);
        setReview(r);
        if (isProcessing(r)) {
          beginPolling();
        } else if (isReadyToEdit(r)) {
          setPhase('edit');
        } else {
          setPhase('intro');
        }
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : 'Could not load this feedback session.');
        setPhase('error');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, sessionToken, token]);

  // --- voice call lifecycle: live -> ended transitions into processing -----
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
        // V1-style: the interviewer is done the moment the call ends. Drafting
        // runs server-side (Lambda) and the backend emails a review+approve link
        // when it's ready (send_happy_path_emails). Don't trap them on a spinner
        // or force inline review — show "submitted" and let them go.
        setPhase('submitted');
      }
    }
  }, [call.status, call.lastError, phase]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  const startCall = useCallback(
    async (redo: boolean) => {
      if (!sessionToken) return;
      setError(null);
      setPhase('calling');
      try {
        const { voice_session_token } = await startVoice(token, sessionToken, redo);
        await call.start(voice_session_token);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Could not start the voice session.');
        setPhase('error');
      }
    },
    [token, sessionToken, call],
  );

  const endCall = useCallback(async () => {
    await call.end();
    setPhase('submitted');
  }, [call]);

  // --- render --------------------------------------------------------------
  if (phase === 'loading') {
    return (
      <Centered>
        <Loader2 className="h-5 w-5 animate-spin text-text-secondary" />
      </Centered>
    );
  }

  if (phase === 'error') {
    return (
      <Centered>
        <div className="flex max-w-sm flex-col items-center gap-4 text-center">
          <AlertCircle className="h-6 w-6 text-red-600" />
          <p className="text-[13px] text-text-secondary">{error}</p>
          <Button id="feedback-error-retry" variant="secondary" onClick={() => startCall(true)}>
            Try again
          </Button>
        </div>
      </Centered>
    );
  }

  if (phase === 'submitted') {
    return (
      <Centered>
        <div className="flex max-w-sm flex-col items-center gap-3 text-center">
          <BrandIcon id="feedback-submitted-icon" className="h-8 w-8 text-charcoal" />
          <h1 id="feedback-submitted-title" className="font-semibold text-charcoal text-lg">
            Feedback submitted
          </h1>
          <p id="feedback-submitted-message" className="text-[13px] text-text-secondary">
            Thanks! We're drafting your feedback now and will email you a link to review and approve
            it shortly. You can safely close this window.
          </p>
        </div>
      </Centered>
    );
  }

  if (phase === 'done') {
    return (
      <Centered>
        <div className="flex max-w-sm flex-col items-center gap-3 text-center">
          <BrandIcon className="h-8 w-8 text-charcoal" />
          <h1 className="font-semibold text-charcoal text-lg">Thank you</h1>
          <p className="text-[13px] text-text-secondary">
            Your feedback has been approved and submitted. You can close this window.
          </p>
        </div>
      </Centered>
    );
  }

  if (phase === 'processing') {
    return (
      <Centered>
        <div className="flex max-w-sm flex-col items-center gap-3 text-center">
          <Loader2 className="h-6 w-6 animate-spin text-text-secondary" />
          <p id="feedback-processing-message" className="text-[13px] text-text-secondary">
            Drafting your feedback — this usually takes a minute or two.
          </p>
          <p id="feedback-processing-hint" className="text-[12px] text-text-tertiary">
            You can safely close this tab — your feedback is saved. Reopen this link anytime to
            review and edit it.
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

  if (phase === 'edit' && review && sessionToken) {
    return (
      <FeedbackEdit
        token={token}
        sessionToken={sessionToken}
        review={review}
        onApproved={() => {
          // Do NOT clear the session here: the initial-load guard redirects to
          // /verify whenever sessionToken is null, so clearing it the instant the
          // user approves bounces them back into the OTP flow (endless approve ->
          // verify -> approve loop). The session expires on its own (24h); the
          // 'done' screen is terminal.
          setPhase('done');
        }}
        onRerecord={() => startCall(true)}
      />
    );
  }

  // intro. If we land here with a non-terminal voice session already on the
  // row (an abandoned/crashed prior attempt), starting with redo=false would
  // 409 ("already active"). A completed session WITH usable feedback never
  // reaches intro (it routes to phase='edit'), so an active/completed status
  // here means there is nothing to preserve — start over cleanly with redo=true.
  const hasStaleVoiceSession =
    review?.feedback_voice_session_status === 'active' ||
    review?.feedback_voice_session_status === 'completed';
  return (
    <Centered>
      <div className="flex max-w-sm flex-col items-center gap-5 text-center">
        <BrandIcon className="h-8 w-8 text-charcoal" />
        <div className="flex flex-col gap-1">
          <h1 className="font-semibold text-charcoal text-lg">Share your interview feedback</h1>
          {session && (
            <p className="text-[13px] text-text-secondary">
              {session.candidate_name} · {session.round_name}
            </p>
          )}
        </div>
        <p className="text-[13px] text-text-secondary">
          OpenRecruiting will walk you through the scorecard in a short voice conversation, then draft your
          feedback for you to review and edit.
        </p>
        <Button id="feedback-start-voice" size="lg" onClick={() => startCall(hasStaleVoiceSession)}>
          Start voice feedback
        </Button>
      </div>
    </Centered>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <main id="feedback-main" className="flex min-h-dvh items-center justify-center bg-canvas px-4">
      {children}
    </main>
  );
}

export default function FeedbackPage() {
  return (
    <Suspense
      fallback={
        <Centered>
          <Loader2 className="h-5 w-5 animate-spin text-text-secondary" />
        </Centered>
      }
    >
      <FeedbackCallProvider>
        <FeedbackInner />
      </FeedbackCallProvider>
    </Suspense>
  );
}
