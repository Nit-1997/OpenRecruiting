'use client';

import { AlertCircle, CheckCircle, Loader2 } from 'lucide-react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { BrandIcon } from '@/components/icons/brand-icons';
import { Button } from '@/components/ui/button';
import { useFeedbackSession } from '@/hooks/use-feedback-session';
import { getSupabaseClient } from '@/lib/supabase';
import {
  type FeedbackContext,
  getContext,
  platformAuth,
  sendOtp,
  verifyOtp,
} from '@/services/public-feedback';

const OTP_LENGTH = 6;
const RESEND_COOLDOWN_S = 60;

type Stage = 'loading' | 'otp' | 'openrecruiting' | 'locked' | 'error' | 'success';

function VerifyInner() {
  const router = useRouter();
  const params = useParams<{ token: string }>();
  const searchParams = useSearchParams();
  const token = params.token;

  const { set: setSessionToken, sessionToken, ready } = useFeedbackSession(token);

  const [stage, setStage] = useState<Stage>('loading');
  const [ctx, setCtx] = useState<FeedbackContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [otp, setOtp] = useState<string[]>(Array(OTP_LENGTH).fill(''));
  const [submitting, setSubmitting] = useState(false);
  const [resendIn, setResendIn] = useState(0);
  const [lockedSeconds, setLockedSeconds] = useState(0);
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);
  const autoVerifiedRef = useRef(false);

  const feedbackUrl = `/feedback/${token}/feedback`;

  const succeedWith = useCallback(
    (sessionToken: string) => {
      setSessionToken(sessionToken);
      setStage('success');
      router.replace(feedbackUrl);
    },
    [setSessionToken, router, feedbackUrl],
  );

  // --- bootstrap -----------------------------------------------------------
  // biome-ignore lint/correctness/useExhaustiveDependencies: one-shot bootstrap keyed on token; submitOtp/resend/router are stable and intentionally not re-run triggers
  useEffect(() => {
    if (!ready) return; // wait for the sessionStorage read
    // Client token is the source of truth: if this tab already holds a session,
    // go straight to the portal. Do NOT trust the server's has_active_session
    // for a tab that has no token — that would bounce against the feedback
    // page's own redirect and loop.
    if (sessionToken) {
      router.replace(feedbackUrl);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const context = await getContext(token);
        if (cancelled) return;
        setCtx(context);

        if (context.requires_platform_login) {
          setStage('openrecruiting');
          return;
        }
        // OTP path — auto-send unless a magic-link code is present.
        const urlOtp = searchParams.get('otp');
        if (urlOtp && /^\d{6}$/.test(urlOtp) && !autoVerifiedRef.current) {
          autoVerifiedRef.current = true;
          setOtp(urlOtp.split(''));
          setStage('otp');
          void submitOtp(urlOtp);
          return;
        }
        setStage('otp');
        void resend();
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : 'Unable to load this feedback link.');
        setStage('error');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, sessionToken, token]);

  // --- openrecruiting-auth (registered interviewers) --------------------------------
  // biome-ignore lint/correctness/useExhaustiveDependencies: runs only when entering the 'openrecruiting' stage; reads token/searchParams at fire time on purpose
  useEffect(() => {
    if (stage !== 'openrecruiting') return;
    if (searchParams.get('platform_auth') !== 'pending') return;
    (async () => {
      try {
        const supabase = getSupabaseClient();
        const {
          data: { session },
        } = await supabase.auth.getSession();
        if (!session?.access_token) return; // not signed in yet; button handles it
        setSubmitting(true);
        const res = await platformAuth(token, session.access_token);
        if (res.success && res.session_token) {
          succeedWith(res.session_token);
        } else {
          setError(res.error ?? 'Could not verify your OpenRecruiting account.');
          setStage('error');
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Sign-in verification failed.');
        setStage('error');
      } finally {
        setSubmitting(false);
      }
    })();
  }, [stage]);

  // --- resend cooldown ticker ----------------------------------------------
  useEffect(() => {
    if (resendIn <= 0) return;
    const id = setInterval(() => setResendIn((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(id);
  }, [resendIn]);

  // --- lockout ticker ------------------------------------------------------
  useEffect(() => {
    if (lockedSeconds <= 0) return;
    const id = setInterval(() => {
      setLockedSeconds((s) => {
        if (s <= 1) {
          setStage('otp');
          return 0;
        }
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [lockedSeconds]);

  const resend = useCallback(async () => {
    try {
      const res = await sendOtp(token);
      setResendIn(res.retry_after_seconds ?? RESEND_COOLDOWN_S);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not send the code. Try again.');
    }
  }, [token]);

  const submitOtp = useCallback(
    async (code: string) => {
      if (code.length !== OTP_LENGTH) return;
      setSubmitting(true);
      setError(null);
      try {
        const res = await verifyOtp(token, code);
        if (res.success && res.session_token) {
          succeedWith(res.session_token);
          return;
        }
        if (res.locked_until) {
          const ms = new Date(res.locked_until).getTime() - Date.now();
          setLockedSeconds(Math.max(1, Math.ceil(ms / 1000)));
          setStage('locked');
          return;
        }
        const remaining = res.attempts_remaining;
        setError(
          res.error ??
            (typeof remaining === 'number'
              ? `Incorrect code. ${remaining} attempt${remaining === 1 ? '' : 's'} left.`
              : 'Incorrect code.'),
        );
        setOtp(Array(OTP_LENGTH).fill(''));
        inputRefs.current[0]?.focus();
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Verification failed. Try again.');
      } finally {
        setSubmitting(false);
      }
    },
    [token, succeedWith],
  );

  const handleChange = (i: number, value: string) => {
    if (!/^\d*$/.test(value)) return;
    const next = [...otp];
    next[i] = value.slice(-1);
    setOtp(next);
    if (value && i < OTP_LENGTH - 1) inputRefs.current[i + 1]?.focus();
    const joined = next.join('');
    if (joined.length === OTP_LENGTH && !next.includes('')) void submitOtp(joined);
  };

  const handleKeyDown = (i: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Backspace' && !otp[i] && i > 0) inputRefs.current[i - 1]?.focus();
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    e.preventDefault();
    const text = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, OTP_LENGTH);
    if (!text) return;
    const next = Array(OTP_LENGTH).fill('');
    text.split('').forEach((d, idx) => {
      next[idx] = d;
    });
    setOtp(next);
    if (text.length === OTP_LENGTH) void submitOtp(text);
    else inputRefs.current[text.length]?.focus();
  };

  // --- render --------------------------------------------------------------
  return (
    <main
      id="feedback-verify-main"
      className="flex min-h-dvh items-center justify-center bg-canvas px-4"
    >
      <div
        id="feedback-verify-card"
        className="w-full max-w-md rounded-card-lg border border-border bg-tile p-8 shadow-sm"
      >
        <div className="mb-6 flex flex-col items-center text-center">
          <BrandIcon className="mb-3 h-8 w-8 text-charcoal" />
          <h1 id="feedback-verify-title" className="font-semibold text-charcoal text-lg">
            Interview feedback
          </h1>
          {ctx?.candidate_name && (
            <p className="mt-1 text-[13px] text-text-secondary">
              {ctx.candidate_name}
              {ctx.round_name ? ` · ${ctx.round_name}` : ''}
            </p>
          )}
        </div>

        {stage === 'loading' && (
          <div className="flex flex-col items-center gap-2 py-8 text-text-secondary">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span className="text-[13px]">Loading…</span>
          </div>
        )}

        {stage === 'success' && (
          <div className="flex flex-col items-center gap-2 py-8 text-charcoal">
            <CheckCircle className="h-6 w-6 text-green-600" />
            <span className="text-[13px]">Verified — taking you in…</span>
          </div>
        )}

        {stage === 'error' && (
          <div className="flex flex-col items-center gap-4 py-6 text-center">
            <AlertCircle className="h-6 w-6 text-red-600" />
            <p className="text-[13px] text-text-secondary">{error}</p>
            <Button
              id="feedback-verify-retry"
              variant="secondary"
              onClick={() => location.reload()}
            >
              Try again
            </Button>
          </div>
        )}

        {stage === 'openrecruiting' && (
          <div className="flex flex-col items-center gap-4 py-4 text-center">
            <p className="text-[13px] text-text-secondary">
              {ctx?.email_hint
                ? `This feedback link is tied to your OpenRecruiting account (${ctx.email_hint}). Sign in to continue.`
                : 'This feedback link is tied to your OpenRecruiting account. Sign in to continue.'}
            </p>
            <Button
              id="feedback-verify-sso-signin"
              disabled={submitting}
              onClick={() =>
                router.push(
                  `/login?redirect=${encodeURIComponent(`/feedback/${token}/verify?platform_auth=pending`)}`,
                )
              }
            >
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Sign in with OpenRecruiting'}
            </Button>
          </div>
        )}

        {stage === 'locked' && (
          <div className="flex flex-col items-center gap-2 py-6 text-center">
            <AlertCircle className="h-6 w-6 text-amber-600" />
            <p className="text-[13px] text-text-secondary">
              Too many attempts. Try again in {Math.floor(lockedSeconds / 60)}:
              {String(lockedSeconds % 60).padStart(2, '0')}.
            </p>
          </div>
        )}

        {stage === 'otp' && (
          <div className="flex flex-col gap-5">
            <p className="text-center text-[13px] text-text-secondary">
              Enter the 6-digit code we emailed
              {ctx?.email_hint ? ` to ${ctx.email_hint}` : ''}.
            </p>
            <div className="flex justify-center gap-2" onPaste={handlePaste}>
              {otp.map((digit, i) => (
                <input
                  // biome-ignore lint/suspicious/noArrayIndexKey: fixed-length OTP slots
                  key={i}
                  id={`feedback-otp-${i}`}
                  ref={(el) => {
                    inputRefs.current[i] = el;
                  }}
                  inputMode="numeric"
                  maxLength={1}
                  value={digit}
                  disabled={submitting}
                  onChange={(e) => handleChange(i, e.target.value)}
                  onKeyDown={(e) => handleKeyDown(i, e)}
                  className="h-12 w-11 rounded-input border border-border bg-canvas text-center font-medium text-charcoal text-lg focus-visible:border-charcoal focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/15"
                />
              ))}
            </div>

            {error && <p className="text-center text-[12px] text-red-600">{error}</p>}
            {submitting && (
              <div className="flex items-center justify-center gap-2 text-text-secondary">
                <Loader2 className="h-4 w-4 animate-spin" />
                <span className="text-[12px]">Verifying…</span>
              </div>
            )}

            <div className="flex items-center justify-center">
              <Button
                id="feedback-otp-resend"
                variant="ghost"
                size="sm"
                disabled={resendIn > 0}
                onClick={() => void resend()}
              >
                {resendIn > 0 ? `Resend code in ${resendIn}s` : 'Resend code'}
              </Button>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}

export default function FeedbackVerifyPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-dvh items-center justify-center bg-canvas">
          <Loader2 className="h-5 w-5 animate-spin text-text-secondary" />
        </main>
      }
    >
      <VerifyInner />
    </Suspense>
  );
}
