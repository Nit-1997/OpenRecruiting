"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Header } from "@/components/ui/header";
import { Checkbox } from "@/components/ui/checkbox";
import { TermsModal } from "@/components/ui/terms-modal";
import { Loader2, AlertCircle, CheckCircle } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { gateAndRedirect } from "@/lib/auth/gate";
import { useAnalytics } from "@/hooks/useAnalytics";

const API_URL = process.env.NEXT_PUBLIC_API_V2_URL || "http://localhost:8000";
const APP_URL = process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3005";

export default function SetPasswordPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isCheckingSession, setIsCheckingSession] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [userName, setUserName] = useState<string>("");
  const [agreedToTerms, setAgreedToTerms] = useState(false);
  const [showTermsModal, setShowTermsModal] = useState(false);
  const { trackEvent } = useAnalytics();

  useEffect(() => {
    const checkSession = async () => {
      const timeout = setTimeout(() => {
        setIsCheckingSession(false);
      }, 3000);

      try {
        const supabase = createClient();

        const hash = window.location.hash;
        if (hash && hash.includes("access_token")) {
          const params = new URLSearchParams(hash.substring(1));
          const accessToken = params.get("access_token");
          const refreshToken = params.get("refresh_token");

          if (accessToken && refreshToken) {
            await supabase.auth.setSession({
              access_token: accessToken,
              refresh_token: refreshToken,
            });
            window.history.replaceState(null, "", "/set-password");
          }
        }

        const { data: { session } } = await supabase.auth.getSession();
        clearTimeout(timeout);
        if (!session) {
          router.push("/login");
        } else {
          const fullName = session.user?.user_metadata?.full_name || "";
          setUserName(fullName);
          setIsCheckingSession(false);
        }
      } catch {
        clearTimeout(timeout);
        router.push("/login");
      }
    };
    checkSession();
  }, [router]);

  const handleSetPassword = async (e: React.FormEvent) => {
    e.preventDefault();

    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const supabase = createClient();
      const { error } = await supabase.auth.updateUser({
        password: password,
        data: { password_set: true },
      });

      if (error) {
        trackEvent("auth_password_set_failed", { error: error.message });
        setError(error.message);
      } else {
        const { data: { session } } = await supabase.auth.getSession();
        if (session?.access_token) {
          try {
            await fetch(`${API_URL}/api/v2/auth/complete-onboarding`, {
              method: "POST",
              headers: {
                "Authorization": `Bearer ${session.access_token}`,
                "Content-Type": "application/json"
              }
            });
          } catch {
          }
        }

        trackEvent("auth_password_set");
        setSuccess(true);
        // Gate before final dashboard redirect — set-password can be reached via a
        // password-reset flow that bypasses the OAuth callback gate, so we re-check here.
        const { data: { session: gateSession } } = await supabase.auth.getSession();
        if (!gateSession) {
          setError("Session expired. Please sign in again.");
          return;
        }
        setTimeout(() => {
          void gateAndRedirect({ supabase, accessToken: gateSession.access_token, target: `${APP_URL}/dashboard` });
        }, 2000);
      }
    } catch {
      trackEvent("auth_password_set_failed", { error: "Failed to set password. Please try again." });
      setError("Failed to set password. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  if (isCheckingSession) {
    return (
      <div id="set-password-page" className="min-h-screen bg-[#FAF9F7]">
        <Header variant="light" />
        <div id="set-password-loading" className="pt-24 flex items-center justify-center min-h-[calc(100vh-5rem)]">
          <Loader2 className="w-8 h-8 animate-spin text-primary" />
        </div>
      </div>
    );
  }

  return (
    <div id="set-password-page" className="min-h-screen bg-[#FAF9F7]">
      <Header variant="light" />
      <main id="set-password-content" className="pt-24 flex items-center justify-center min-h-[calc(100vh-5rem)] px-6">
        <div id="set-password-form-wrapper" className="w-full max-w-md">
          <div id="set-password-card" className="bg-[#F2F0ED] border border-[#E5E3DF] rounded-2xl p-8 md:p-10">
            <div id="set-password-header" className="mb-8">
              <h1 id="set-password-title" className="font-display text-3xl md:text-4xl font-light text-[#111111] mb-2">
                Welcome to OpenRecruiting
              </h1>
              {userName && (
                <p id="set-password-user-name" className="font-display text-3xl md:text-4xl font-light text-primary mb-4">
                  {userName}
                </p>
              )}
              <p id="set-password-subtitle" className="text-[#555555]">
                Please set your password to continue.
              </p>
            </div>

            {error && (
              <div
                id="set-password-error"
                className="mb-6 p-4 rounded-xl flex items-center gap-3 bg-red-50 border border-red-200"
              >
                <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0" />
                <p id="set-password-error-text" className="text-sm text-red-800">
                  {error}
                </p>
              </div>
            )}

            {success && (
              <div
                id="set-password-success"
                className="mb-6 p-4 rounded-xl flex items-center gap-3 bg-green-50 border border-green-200"
              >
                <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0" />
                <p id="set-password-success-text" className="text-sm text-green-800">
                  Password set successfully! Redirecting to dashboard...
                </p>
              </div>
            )}

            <form id="set-password-form" className="space-y-4" onSubmit={handleSetPassword}>
              <div id="new-password-field">
                <Input
                  id="new-password-input"
                  type="password"
                  placeholder="New password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="h-12 bg-white border-[#E5E3DF] rounded-xl"
                  required
                  disabled={isLoading || success}
                  minLength={8}
                />
              </div>

              <div id="confirm-password-field">
                <Input
                  id="confirm-password-input"
                  type="password"
                  placeholder="Confirm password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="h-12 bg-white border-[#E5E3DF] rounded-xl"
                  required
                  disabled={isLoading || success}
                  minLength={8}
                />
              </div>

              <div id="terms-checkbox-field" className="flex items-start gap-3">
                <Checkbox
                  id="terms-checkbox"
                  checked={agreedToTerms}
                  onCheckedChange={(checked) => {
                    setAgreedToTerms(checked === true);
                    if (checked === true) {
                      trackEvent("auth_terms_accepted");
                    }
                  }}
                  disabled={isLoading || success}
                  className="mt-0.5"
                />
                <label
                  id="terms-checkbox-label"
                  htmlFor="terms-checkbox"
                  className="text-sm text-[#555555] leading-snug cursor-pointer select-none"
                >
                  I agree to the{" "}
                  <span
                    id="terms-link"
                    className="text-primary underline cursor-pointer"
                    onClick={(e) => {
                      e.preventDefault();
                      setShowTermsModal(true);
                    }}
                  >
                    Terms of Service
                  </span>
                </label>
              </div>

              <Button
                id="set-password-btn"
                type="submit"
                className="w-full h-12 bg-[#111111] text-white hover:bg-[#111111]/90 rounded-full text-base font-medium"
                disabled={isLoading || success || !password.trim() || !confirmPassword.trim() || !agreedToTerms}
              >
                {isLoading ? (
                  <>
                    <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                    Setting password...
                  </>
                ) : (
                  "Set Password"
                )}
              </Button>
            </form>
          </div>

          <p id="password-requirements" className="mt-6 text-center text-sm text-[#555555]">
            Password must be at least 8 characters long.
          </p>
        </div>
      </main>

      <TermsModal isOpen={showTermsModal} onClose={() => setShowTermsModal(false)} />
    </div>
  );
}
