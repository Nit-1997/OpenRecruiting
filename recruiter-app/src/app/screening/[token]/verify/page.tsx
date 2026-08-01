'use client';

import { AlertCircle, CheckCircle, Clock, Loader2 } from 'lucide-react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { BrandIcon } from '@/components/icons/brand-icons';
import { Button } from '@/components/ui/button';
import { useScreeningSession } from '@/hooks/use-screening-session';
import {
  getContext,
  SCREENING_EXPIRED_STATUS,
  type ScreeningContext,
  sendOtp,
  verifyOtp,
} from '@/services/public-screening';
import { ServiceError } from '@/services/service-error';

const OTP_LENGTH = 6;
const RESEND_COOLDOWN_S = 60;

// No OpenRecruiting-auth SSO stage: screening candidates are external (OTP-only). The
// NEW stage vs the feedback portal is `expired`, driven by the backend 410.
type Stage = 'loading' | 'otp' | 'expired' | 'locked' | 'error' | 'success';

function isExpired(e: unknown): boolean {
  return e instanceof ServiceError && e.httpStatus === SCREENING_EXPIRED_STATUS;
}

function VerifyInner() {
  const router = useRouter();
  const params = useParams<{ token: string }>();
  const searchParams = useSearchParams();
  const token = params.token;

  const { set: setSessionToken, sessionToken, ready } = useScreeningSession(token);

  const [stage, setStage] = useState<Stage>('loading');
  const [ctx, setCtx] = useState<ScreeningContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [otp, setOtp] = useState<string[]>(Array(OTP_LENGTH).fill(''));
  const [submitting, setSubmitting] = useState(false);
  const [resendIn, setResendIn] = useState(0);
  const [lockedSeconds, setLockedSeconds] = useState(0);
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);
  const autoVerifiedRef = useRef(false);

  const callUrl = `/screening/${token}/call`;

  const succeedWith = useCallback(
    (newSessionToken: string) => {
      setSessionToken(newSessionToken);
      setStage('success');
      router.replace(callUrl);
    },
    [setSessionToken, router, callUrl],
  );

  const resend = useCallback(async () => {
    try {
      const res = await sendOtp(token);
      setResendIn(res.retry_after_seconds ?? RESEND_COOLDOWN_S);
      setError(null);
    } catch (e) {
      if (isExpired(e)) {
        setStage('expired');
        return;
      }
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
        if (isExpired(e)) {
          setStage('expired');
          return;
        }
        setError(e instanceof Error ? e.message : 'Verification failed. Try again.');
      } finally {
        setSubmitting(false);
      }
    },
    [token, succeedWith],
  );

  // --- bootstrap -----------------------------------------------------------
  // biome-ignore lint/correctness/useExhaustiveDependencies: one-shot bootstrap keyed on token; submitOtp/resend/router are stable and intentionally not re-run triggers
  useEffect(() => {
    if (!ready) return; // wait for the sessionStorage read
    // Client token is the source of truth: if this tab already holds a session,
    // go straight to the call page. Do NOT trust the server's has_active_session
    // for a tab that has no token — that would bounce against the call page's own
    // redirect and loop.
    if (sessionToken) {
      router.replace(callUrl);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const context = await getContext(token);
        if (cancelled) return;
        setCtx(context);

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
        if (isExpired(e)) {
          setStage('expired');
          return;
        }
        setError(e instanceof Error ? e.message : 'Unable to load this screening link.');
        setStage('error');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, sessionToken, token]);

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
      id="screening-verify-main"
      className="flex min-h-dvh items-center justify-center bg-canvas px-4"
    >
      <div
        id="screening-verify-card"
        className="w-full max-w-md rounded-card-lg border border-border bg-tile p-8 shadow-sm"
      >
        <div className="mb-6 flex flex-col items-center text-center">
          <BrandIcon id="screening-verify-logo" className="mb-3 h-8 w-8 text-charcoal" />
          <h1 id="screening-verify-title" className="font-semibold text-charcoal text-lg">
            Screening interview
          </h1>
          {ctx?.role_title && (
            <p id="screening-verify-subtitle" className="mt-1 text-[13px] text-text-secondary">
              {ctx.role_title}
              {ctx.round_name ? ` · ${ctx.round_name}` : ''}
            </p>
          )}
        </div>

        {stage === 'loading' && (
          <div
            id="screening-verify-loading"
            className="flex flex-col items-center gap-2 py-8 text-text-secondary"
          >
            <Loader2 id="screening-verify-loading-spinner" className="h-5 w-5 animate-spin" />
            <span id="screening-verify-loading-text" className="text-[13px]">
              Loading…
            </span>
          </div>
        )}

        {stage === 'success' && (
          <div
            id="screening-verify-success"
            className="flex flex-col items-center gap-2 py-8 text-charcoal"
          >
            <CheckCircle id="screening-verify-success-icon" className="h-6 w-6 text-green-600" />
            <span id="screening-verify-success-text" className="text-[13px]">
              Verified — taking you in…
            </span>
          </div>
        )}

        {stage === 'expired' && (
          <div
            id="screening-verify-expired"
            className="flex flex-col items-center gap-3 py-6 text-center"
          >
            <Clock id="screening-verify-expired-icon" className="h-6 w-6 text-amber-600" />
            <p id="screening-verify-expired-text" className="text-[13px] text-text-secondary">
              This screening link has expired. Please contact the recruiter who invited you for a
              new link.
            </p>
          </div>
        )}

        {stage === 'error' && (
          <div
            id="screening-verify-error"
            className="flex flex-col items-center gap-4 py-6 text-center"
          >
            <AlertCircle id="screening-verify-error-icon" className="h-6 w-6 text-red-600" />
            <p id="screening-verify-error-text" className="text-[13px] text-text-secondary">
              {error}
            </p>
            <Button
              id="screening-verify-retry"
              variant="secondary"
              onClick={() => location.reload()}
            >
              Try again
            </Button>
          </div>
        )}

        {stage === 'locked' && (
          <div
            id="screening-verify-locked"
            className="flex flex-col items-center gap-2 py-6 text-center"
          >
            <AlertCircle id="screening-verify-locked-icon" className="h-6 w-6 text-amber-600" />
            <p id="screening-verify-locked-text" className="text-[13px] text-text-secondary">
              Too many attempts. Try again in {Math.floor(lockedSeconds / 60)}:
              {String(lockedSeconds % 60).padStart(2, '0')}.
            </p>
          </div>
        )}

        {stage === 'otp' && (
          <div id="screening-verify-otp" className="flex flex-col gap-5">
            <p
              id="screening-otp-instructions"
              className="text-center text-[13px] text-text-secondary"
            >
              Enter the 6-digit code we emailed
              {ctx?.email_hint ? ` to ${ctx.email_hint}` : ''}.
            </p>
            <fieldset
              id="screening-otp-inputs"
              className="flex justify-center gap-2 border-0 p-0"
              onPaste={handlePaste}
            >
              <legend id="screening-otp-legend" className="sr-only">
                One-time passcode
              </legend>
              {otp.map((digit, i) => (
                <input
                  // biome-ignore lint/suspicious/noArrayIndexKey: fixed-length OTP slots
                  key={i}
                  id={`screening-otp-${i}`}
                  aria-label={`Digit ${i + 1} of ${OTP_LENGTH}`}
                  ref={(el) => {
                    inputRefs.current[i] = el;
                  }}
                  inputMode="numeric"
                  autoComplete={i === 0 ? 'one-time-code' : 'off'}
                  maxLength={1}
                  value={digit}
                  disabled={submitting}
                  onChange={(e) => handleChange(i, e.target.value)}
                  onKeyDown={(e) => handleKeyDown(i, e)}
                  className="h-12 w-11 rounded-input border border-border bg-canvas text-center font-medium text-charcoal text-lg focus-visible:border-charcoal focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/15"
                />
              ))}
            </fieldset>

            {error && (
              <p id="screening-otp-error" className="text-center text-[12px] text-red-600">
                {error}
              </p>
            )}
            {submitting && (
              <div
                id="screening-otp-verifying"
                className="flex items-center justify-center gap-2 text-text-secondary"
              >
                <Loader2 className="h-4 w-4 animate-spin" />
                <span className="text-[12px]">Verifying…</span>
              </div>
            )}

            <div className="flex items-center justify-center">
              <Button
                id="screening-otp-resend"
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

export default function ScreeningVerifyPage() {
  return (
    <Suspense
      fallback={
        <main
          id="screening-verify-suspense"
          className="flex min-h-dvh items-center justify-center bg-canvas"
        >
          <Loader2 className="h-5 w-5 animate-spin text-text-secondary" />
        </main>
      }
    >
      <VerifyInner />
    </Suspense>
  );
}
