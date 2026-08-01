'use client';

import { AlertCircle, CheckCircle, Loader2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { BrandIcon } from '@/components/icons/brand-icons';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { getSupabaseClient } from '@/lib/supabase';

export default function SetPasswordPage() {
  const router = useRouter();
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isCheckingSession, setIsCheckingSession] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    const bootstrap = async () => {
      const timeout = setTimeout(() => setIsCheckingSession(false), 3000);
      try {
        const supabase = getSupabaseClient();
        const hash = window.location.hash;
        if (hash.includes('access_token')) {
          const params = new URLSearchParams(hash.substring(1));
          const accessToken = params.get('access_token');
          const refreshToken = params.get('refresh_token');
          if (accessToken && refreshToken) {
            await supabase.auth.setSession({ access_token: accessToken, refresh_token: refreshToken });
            window.history.replaceState(null, '', '/set-password');
          }
        }
        const { data: { session } } = await supabase.auth.getSession();
        clearTimeout(timeout);
        if (!session) {
          router.replace('/login');
        } else {
          setIsCheckingSession(false);
        }
      } catch {
        clearTimeout(timeout);
        router.replace('/login');
      }
    };
    void bootstrap();
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const supabase = getSupabaseClient();
      const { error: updateError } = await supabase.auth.updateUser({ password });
      if (updateError) {
        setError(updateError.message);
        return;
      }
      setSuccess(true);
      setTimeout(() => router.replace('/'), 1500);
    } catch {
      setError('Failed to set password. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  if (isCheckingSession) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#FAF9F7]">
        <Loader2 className="h-8 w-8 animate-spin text-[#111111]" />
      </div>
    );
  }

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
        <div className="w-full max-w-md">
          <div className="rounded-2xl border border-[#E5E3DF] bg-[#F2F0ED] p-8 md:p-10">
            <div className="mb-8">
              <h1 className="mb-2 font-display text-3xl font-light text-[#111111] md:text-4xl">
                Welcome to OpenRecruiting
              </h1>
              <p className="text-[#555555]">Set your password to get started.</p>
            </div>

            {error && (
              <div className="mb-6 flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 p-4">
                <AlertCircle className="h-5 w-5 shrink-0 text-red-600" />
                <p className="text-red-800 text-sm">{error}</p>
              </div>
            )}

            {success && (
              <div className="mb-6 flex items-center gap-3 rounded-xl border border-green-200 bg-green-50 p-4">
                <CheckCircle className="h-5 w-5 shrink-0 text-green-600" />
                <p className="text-green-800 text-sm">Password set! Redirecting…</p>
              </div>
            )}

            <form className="space-y-4" onSubmit={handleSubmit}>
              <Input
                id="set-password-new"
                type="password"
                placeholder="New password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="h-12 rounded-xl border-[#E5E3DF] bg-white"
                required
                disabled={isLoading || success}
                minLength={8}
              />
              <Input
                id="set-password-confirm"
                type="password"
                placeholder="Confirm password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="h-12 rounded-xl border-[#E5E3DF] bg-white"
                required
                disabled={isLoading || success}
                minLength={8}
              />
              <Button
                id="set-password-submit"
                type="submit"
                className="h-12 w-full rounded-full bg-[#111111] font-medium text-base text-white hover:bg-[#111111]/90"
                disabled={isLoading || success || !password.trim() || !confirmPassword.trim()}
              >
                {isLoading ? (
                  <>
                    <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                    Setting password…
                  </>
                ) : (
                  'Set Password'
                )}
              </Button>
            </form>
          </div>
          <p className="mt-6 text-center text-[#555555] text-sm">
            Password must be at least 8 characters.
          </p>
        </div>
      </main>
    </div>
  );
}
