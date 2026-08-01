"use client";

import { useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Header } from "@/components/ui/header";
import { Loader2, AlertCircle } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { gateAndRedirect } from "@/lib/auth/gate";
import { useAnalytics } from "@/hooks/useAnalytics";
import dynamic from "next/dynamic";

const CalendlyModal = dynamic(
  () => import("@/components/ui/calendly-modal").then((mod) => ({ default: mod.CalendlyModal })),
  { ssr: false },
);

const capturedHash = typeof window !== "undefined" ? window.location.hash : "";
const APP_URL = process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3005";

function isValidRedirect(path: string): boolean {
  if (!path || !path.startsWith('/') || path.startsWith('//')) return false;
  try {
    const url = new URL(path, window.location.origin);
    return url.origin === window.location.origin;
  } catch {
    return false;
  }
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isCheckingSession, setIsCheckingSession] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCalendly, setShowCalendly] = useState(false);
  const { trackEvent } = useAnalytics();

  const urlError = searchParams.get("error");
  const redirectParam = searchParams.get("redirect");

  useEffect(() => {
    if (redirectParam && isValidRedirect(redirectParam)) {
      document.cookie = `auth_redirect=${encodeURIComponent(redirectParam)}; path=/; max-age=3600; SameSite=Lax`;
    }
  }, [redirectParam]);

  useEffect(() => {
    const supabase = createClient();

    const handleRedirect = async (
      session:
        | { access_token: string; user: { app_metadata?: { provider?: string }; user_metadata?: { password_set?: boolean } } }
        | null,
    ) => {
      if (session) {
        const provider = session.user?.app_metadata?.provider || 'email';
        const isGoogleUser = provider === 'google';
        const needsPassword = !isGoogleUser && !session.user?.user_metadata?.password_set;
        console.log("Redirecting, needs password:", needsPassword);
        if (needsPassword) {
          // /set-password gates internally before its own dashboard redirect,
          // so we can push directly here (and the page itself relies on the session).
          router.push("/set-password");
          return;
        }
        const useRedirectParam = redirectParam && isValidRedirect(redirectParam);
        // OAuth consent + other landing-owned routes (/oauth/*) live on
        // landing itself, not on recruiter-app. Keep them on origin.
        const stayOnOrigin = useRedirectParam && redirectParam!.startsWith("/oauth/");
        const target = useRedirectParam
          ? (stayOnOrigin ? `${window.location.origin}${redirectParam}` : `${APP_URL}${redirectParam}`)
          : `${APP_URL}/dashboard`;
        if (useRedirectParam) {
          document.cookie = "auth_redirect=; path=/; max-age=0";
        }
        await gateAndRedirect({ supabase, accessToken: session.access_token, target });
      }
    };

    const processAuth = async () => {
      const hash = capturedHash || window.location.hash;
      console.log("Processing hash:", hash.substring(0, 50) + "...");
      if (hash && hash.includes("access_token")) {
        console.log("Found hash tokens, parsing...");
        const params = new URLSearchParams(hash.substring(1));
        const accessToken = params.get("access_token");
        const refreshToken = params.get("refresh_token");

        if (accessToken && refreshToken) {
          console.log("Setting session manually...");
          const { data, error } = await supabase.auth.setSession({
            access_token: accessToken,
            refresh_token: refreshToken,
          });

          window.history.replaceState(null, "", "/login");

          if (error) {
            console.error("Failed to set session:", error.message);
            setError(`Authentication failed: ${error.message}`);
            setIsCheckingSession(false);
            return;
          }

          if (data.session) {
            console.log("Session set successfully!");
            await handleRedirect(data.session);
            return;
          }
        }
      }

      const { data: { user }, error: userError } = await supabase.auth.getUser();
      console.log("User check:", !!user);
      if (user && !userError) {
        // handleRedirect needs an access_token to call the gate; getUser() does
        // not return one, so re-fetch the session here.
        const { data: sessionData } = await supabase.auth.getSession();
        if (sessionData.session) {
          await handleRedirect(sessionData.session);
        } else {
          setIsCheckingSession(false);
        }
      } else {
        setIsCheckingSession(false);
      }
    };

    processAuth();
  }, [router, redirectParam]);

  useEffect(() => {
    if (urlError === "auth_failed") {
      setError("Authentication failed. Please try again.");
    } else if (urlError === "auth_unavailable") {
      setError("Sign-in is temporarily unavailable. Please try again in a moment.");
    }
  }, [urlError]);

  const handleGoogleSignIn = async () => {
    setIsLoading(true);
    setError(null);
    trackEvent("auth_login_attempted", { method: "google" });
    try {
      const supabase = createClient();
      const { error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: `${window.location.origin}/auth/callback`,
        },
      });
      if (error) {
        trackEvent("auth_login_failed", { method: "google", error: error.message });
        setError(error.message);
        setIsLoading(false);
      }
    } catch {
      trackEvent("auth_login_failed", { method: "google", error: "Failed to sign in with Google. Please try again." });
      setError("Failed to sign in with Google. Please try again.");
      setIsLoading(false);
    }
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password.trim()) return;

    setIsLoading(true);
    setError(null);
    trackEvent("auth_login_attempted", { method: "email_password" });

    try {
      const supabase = createClient();
      const { error } = await supabase.auth.signInWithPassword({
        email: email.trim().toLowerCase(),
        password: password,
      });

      if (error) {
        trackEvent("auth_login_failed", { method: "email_password", error: error.message });
        setError(error.message);
      } else {
        trackEvent("auth_login_succeeded", { method: "email_password" });
        document.cookie = "auth_redirect=; path=/; max-age=0";
        const { data: { session } } = await supabase.auth.getSession();
        if (!session) {
          setError("Sign-in succeeded but no session was created. Please try again.");
          return;
        }
        const valid = redirectParam && isValidRedirect(redirectParam);
        const stayOnOrigin = valid && redirectParam!.startsWith("/oauth/");
        const target = valid
          ? (stayOnOrigin ? `${window.location.origin}${redirectParam}` : `${APP_URL}${redirectParam}`)
          : `${APP_URL}/dashboard`;
        await gateAndRedirect({ supabase, accessToken: session.access_token, target });
        return;
      }
    } catch {
      trackEvent("auth_login_failed", { method: "email_password", error: "Failed to sign in. Please try again." });
      setError("Failed to sign in. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  if (isCheckingSession) {
    return (
      <div id="login-loading" className="flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div id="login-form-wrapper" className="w-full max-w-md">
      <div id="login-card" className="bg-[#F2F0ED] border border-[#E5E3DF] rounded-2xl p-8 md:p-10">
        <div id="login-header" className="mb-8">
          <h1 id="login-title" className="font-display text-3xl md:text-4xl font-light text-[#111111] mb-2">
            Welcome back
          </h1>
          <p id="login-subtitle" className="text-[#555555]">
            Sign in to continue to your dashboard.
          </p>
        </div>

        <Button
          id="login-google-btn"
          type="button"
          onClick={handleGoogleSignIn}
          className="w-full h-12 bg-white border border-[#E5E3DF] text-[#111111] hover:bg-gray-50 rounded-full text-base font-medium flex items-center justify-center gap-3 mb-2"
          disabled={isLoading}
        >
          <svg id="login-google-icon" className="w-5 h-5" viewBox="0 0 24 24">
            <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/>
            <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
            <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
            <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
          </svg>
          Sign in with Google
        </Button>

        <div id="login-divider" className="relative my-6">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-[#E5E3DF]"></div>
          </div>
          <div className="relative flex justify-center text-sm">
            <span className="bg-[#F2F0ED] px-4 text-[#999999]">or sign in with email</span>
          </div>
        </div>

        {error && (
          <div
            id="login-error"
            className="mb-6 p-4 rounded-xl flex items-center gap-3 bg-red-50 border border-red-200"
          >
            <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0" />
            <p id="login-error-text" className="text-sm text-red-800">
              {error}
            </p>
          </div>
        )}

        <form id="login-form" className="space-y-4" onSubmit={handleLogin}>
          <div id="email-field">
            <Input
              id="login-email"
              type="email"
              placeholder="Email address"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="h-12 bg-white border-[#E5E3DF] rounded-xl"
              required
              disabled={isLoading}
            />
          </div>

          <div id="password-field">
            <Input
              id="login-password"
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="h-12 bg-white border-[#E5E3DF] rounded-xl"
              required
              disabled={isLoading}
            />
          </div>

          <Button
            id="login-submit-btn"
            type="submit"
            className="w-full h-12 bg-[#111111] text-white hover:bg-[#111111]/90 rounded-full text-base font-medium"
            disabled={isLoading || !email.trim() || !password.trim()}
          >
            {isLoading ? (
              <>
                <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                Signing in...
              </>
            ) : (
              "Sign In"
            )}
          </Button>
        </form>
      </div>

      <p id="login-help-text" className="mt-6 text-center text-sm text-[#555555]">
        First time? Book demo{" "}
        <button
          id="login-book-demo-link"
          type="button"
          onClick={() => {
            trackEvent("demo_booking_opened", { cta_location: "login_subtext" });
            setShowCalendly(true);
          }}
          className="text-primary hover:underline focus:outline-none"
        >
          here
        </button>{" "}
        to start.
      </p>

      {showCalendly && (
        <CalendlyModal isOpen={showCalendly} onClose={() => setShowCalendly(false)} />
      )}
    </div>
  );
}

export default function LoginPage() {
  return (
    <div id="login-page" className="relative min-h-screen">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/hero-bg.png"
        alt=""
        className="absolute inset-0 w-full h-full object-cover z-0"
      />
      <Header variant="light" />
      <main id="login-content" className="relative z-10 pt-24 flex items-center justify-center min-h-[calc(100vh-5rem)] px-6">
        <Suspense fallback={
          <div className="flex items-center justify-center">
            <Loader2 className="w-8 h-8 animate-spin text-primary" />
          </div>
        }>
          <LoginForm />
        </Suspense>
      </main>
    </div>
  );
}
