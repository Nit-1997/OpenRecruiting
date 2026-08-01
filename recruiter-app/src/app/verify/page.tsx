'use client';

import { AlertCircle, CheckCircle, Loader2 } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useRef, useState } from 'react';
import { BrandIcon } from '@/components/icons/brand-icons';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { V2_API_BASE } from '@/lib/env';
import { getSupabaseClient } from '@/lib/supabase';

function VerifyForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState('');
  const [otp, setOtp] = useState<string[]>(Array(8).fill(''));
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    const emailParam = searchParams.get('email');
    if (emailParam) {
      setEmail(decodeURIComponent(emailParam));
      setTimeout(() => inputRefs.current[0]?.focus(), 100);
    }

    const checkSession = async () => {
      const supabase = getSupabaseClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (session) {
        const needsPassword = !session.user?.user_metadata?.password_set;
        router.replace(needsPassword ? '/set-password' : '/');
      }
    };
    void checkSession();
  }, [router, searchParams]);

  const handleOtpChange = (index: number, value: string) => {
    if (!/^\d*$/.test(value)) return;
    const next = [...otp];
    next[index] = value.slice(-1);
    setOtp(next);
    if (value && index < 7) inputRefs.current[index + 1]?.focus();
  };

  const handleKeyDown = (index: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Backspace' && !otp[index] && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    e.preventDefault();
    const digits = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 8);
    if (digits.length === 8) {
      setOtp(digits.split(''));
      inputRefs.current[7]?.focus();
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = otp.join('');
    if (token.length !== 8) {
      setError('Please enter the complete 8-digit code');
      return;
    }
    if (!email.trim()) {
      setError('Please enter your email address');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const res = await fetch(`${V2_API_BASE}/api/v2/auth/verify-otp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim().toLowerCase(), token }),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(
          res.status === 400 && data.detail
            ? data.detail
            : 'Verification failed. Please check your code and try again.',
        );
        return;
      }

      const supabase = getSupabaseClient();
      const { error: sessionError } = await supabase.auth.setSession({
        access_token: data.access_token,
        refresh_token: data.refresh_token,
      });

      if (sessionError) {
        setError('Failed to establish session. Please try again.');
        return;
      }

      setSuccess(true);
      setTimeout(() => router.replace('/set-password'), 1500);
    } catch {
      setError('Failed to verify. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const emailFromUrl = !!searchParams.get('email');

  return (
    <div className="w-full max-w-md">
      <div className="rounded-2xl border border-[#E5E3DF] bg-[#F2F0ED] p-8 md:p-10">
        <div className="mb-8">
          <h1 className="mb-2 font-display text-3xl font-light text-[#111111] md:text-4xl">
            Verify your email
          </h1>
          <p className="text-[#555555]">
            Enter the 8-digit code sent to {email || 'your email'}.
          </p>
        </div>

        {error && (
          <div className="mb-6 flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 p-4">
            <AlertCircle className="h-5 w-5 shrink-0 text-red-600" />
            <p className="text-sm text-red-800">{error}</p>
          </div>
        )}

        {success && (
          <div className="mb-6 flex items-center gap-3 rounded-xl border border-green-200 bg-green-50 p-4">
            <CheckCircle className="h-5 w-5 shrink-0 text-green-600" />
            <p className="text-sm text-green-800">Verified! Setting up your account…</p>
          </div>
        )}

        <form className="space-y-6" onSubmit={handleSubmit}>
          {!emailFromUrl && (
            <Input
              id="verify-email"
              type="email"
              placeholder="Email address"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="h-12 rounded-xl border-[#E5E3DF] bg-white"
              required
              disabled={isLoading || success}
            />
          )}

          <div>
            <label className="mb-3 block text-sm font-medium text-[#555555]">
              Verification code
            </label>
            <div className="grid grid-cols-8 gap-1.5" onPaste={handlePaste}>
              {otp.map((digit, i) => (
                <Input
                  key={i}
                  id={`verify-otp-${i}`}
                  ref={(el) => {
                    inputRefs.current[i] = el;
                  }}
                  type="text"
                  inputMode="numeric"
                  maxLength={1}
                  value={digit}
                  onChange={(e) => handleOtpChange(i, e.target.value)}
                  onKeyDown={(e) => handleKeyDown(i, e)}
                  className="!h-12 !w-full !px-0 text-center text-xl font-mono bg-white border border-[#C5C3BF] rounded-lg focus:border-[#111111]"
                  disabled={isLoading || success}
                />
              ))}
            </div>
          </div>

          <Button
            id="verify-submit"
            type="submit"
            className="h-12 w-full rounded-full bg-[#111111] font-medium text-base text-white hover:bg-[#111111]/90"
            disabled={isLoading || success || otp.join('').length !== 8 || !email.trim()}
          >
            {isLoading ? (
              <>
                <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                Verifying…
              </>
            ) : (
              'Verify'
            )}
          </Button>
        </form>
      </div>
      <p className="mt-6 text-center text-sm text-[#555555]">
        Need a new code? Contact your administrator.
      </p>
    </div>
  );
}

export default function VerifyPage() {
  return (
    <div className="min-h-screen bg-[#FAF9F7]">
      <header className="flex h-[72px] items-center justify-center px-6">
        <a href="/login" className="inline-flex items-center gap-2 text-[#111111]" aria-label="OpenRecruiting">
          <BrandIcon className="h-[28px] w-[28px] shrink-0" />
          <span className="font-brand text-[24px] leading-none tracking-tight">
            openrecruiting<span className="text-[#111111]/60">.ai</span>
          </span>
        </a>
      </header>
      <main className="flex min-h-[calc(100vh-72px)] items-center justify-center px-6">
        <Suspense fallback={<Loader2 className="h-8 w-8 animate-spin text-[#111111]" />}>
          <VerifyForm />
        </Suspense>
      </main>
    </div>
  );
}
