"use client";

import { useState, useRef, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Header } from "@/components/ui/header";
import { Loader2, AlertCircle, CheckCircle } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { gateAndRedirect } from "@/lib/auth/gate";
import { useAnalytics } from "@/hooks/useAnalytics";
import { getRuntimeConfig } from "@/lib/runtime-config";

const API_URL = getRuntimeConfig().apiV2Url;
const APP_URL = getRuntimeConfig().appUrl || "http://localhost:3005";

function VerifyForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [emailFromUrl, setEmailFromUrl] = useState(false);
  const [otp, setOtp] = useState(["", "", "", "", "", "", "", ""]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);
  const { trackEvent } = useAnalytics();

  useEffect(() => {
    const emailParam = searchParams.get("email");
    if (emailParam) {
      setEmail(decodeURIComponent(emailParam));
      setEmailFromUrl(true);
      setTimeout(() => inputRefs.current[0]?.focus(), 100);
    }

    const checkSession = async () => {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (session) {
        const needsPassword = !session.user?.user_metadata?.password_set;
        if (needsPassword) {
          // /set-password is itself gated — safe to push directly.
          router.push("/set-password");
        } else {
          // Gate before sending the user to the dashboard.
          await gateAndRedirect({ supabase, accessToken: session.access_token, target: `${APP_URL}/dashboard` });
        }
      }
    };
    checkSession();
  }, [router, searchParams]);

  const handleOtpChange = (index: number, value: string) => {
    if (value.length > 1) {
      value = value.slice(-1);
    }

    if (!/^\d*$/.test(value)) {
      return;
    }

    const newOtp = [...otp];
    newOtp[index] = value;
    setOtp(newOtp);

    if (value && index < 7) {
      inputRefs.current[index + 1]?.focus();
    }
  };

  const handleKeyDown = (index: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Backspace" && !otp[index] && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    e.preventDefault();
    const pastedData = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, 8);
    if (pastedData.length === 8) {
      const newOtp = pastedData.split("");
      setOtp(newOtp);
      inputRefs.current[7]?.focus();
    }
  };

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault();

    const token = otp.join("");
    if (token.length !== 8) {
      setError("Please enter the complete 8-digit code");
      return;
    }

    if (!email.trim()) {
      setError("Please enter your email address");
      return;
    }

    setIsLoading(true);
    setError(null);
    trackEvent("auth_otp_submitted");

    try {
      const response = await fetch(`${API_URL}/api/v2/auth/verify-otp`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email.trim().toLowerCase(),
          token: token
        })
      });

      const data = await response.json();

      if (!response.ok) {
        const errorMsg = data.detail || "Verification failed. Please check your code and try again.";
        trackEvent("auth_otp_failed", { error: errorMsg });
        setError(errorMsg);
        return;
      }

      const supabase = createClient();
      const { error: sessionError } = await supabase.auth.setSession({
        access_token: data.access_token,
        refresh_token: data.refresh_token
      });

      if (sessionError) {
        trackEvent("auth_otp_failed", { error: "Failed to establish session. Please try again." });
        setError("Failed to establish session. Please try again.");
        return;
      }

      trackEvent("auth_otp_succeeded");
      setSuccess(true);
      setTimeout(() => {
        window.location.href = "/set-password";
      }, 1500);
    } catch {
      trackEvent("auth_otp_failed", { error: "Failed to verify. Please try again." });
      setError("Failed to verify. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div id="verify-form-wrapper" className="w-full max-w-md">
      <div id="verify-card" className="bg-[#F2F0ED] border border-[#E5E3DF] rounded-2xl p-8 md:p-10">
        <div id="verify-header" className="mb-8">
          <h1 id="verify-title" className="font-display text-3xl md:text-4xl font-light text-[#111111] mb-2">
            Verify Your Email
          </h1>
          <p id="verify-subtitle" className="text-[#555555]">
            Enter your email and the 8-digit code sent to you.
          </p>
        </div>

        {error && (
          <div
            id="verify-error"
            className="mb-6 p-4 rounded-xl flex items-center gap-3 bg-red-50 border border-red-200"
          >
            <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0" />
            <p id="verify-error-text" className="text-sm text-red-800">
              {error}
            </p>
          </div>
        )}

        {success && (
          <div
            id="verify-success"
            className="mb-6 p-4 rounded-xl flex items-center gap-3 bg-green-50 border border-green-200"
          >
            <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0" />
            <p id="verify-success-text" className="text-sm text-green-800">
              Verified! Redirecting to set your password...
            </p>
          </div>
        )}

        <form id="verify-form" className="space-y-6" onSubmit={handleVerify}>
          <div id="verify-email-field">
            <Input
              id="verify-email-input"
              type="email"
              placeholder="Email address"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={`h-12 bg-white border-[#E5E3DF] rounded-xl ${emailFromUrl ? "bg-gray-50" : ""}`}
              required
              disabled={isLoading || success}
              readOnly={emailFromUrl}
            />
            {emailFromUrl && (
              <button
                id="verify-change-email-btn"
                type="button"
                onClick={() => { setEmailFromUrl(false); setEmail(""); }}
                className="mt-2 text-sm text-primary hover:underline"
              >
                Use a different email
              </button>
            )}
          </div>

          <div id="verify-otp-field">
            <label id="verify-otp-label" className="block text-sm font-medium text-[#555555] mb-3">
              Verification Code
            </label>
            <div id="verify-otp-inputs" className="grid grid-cols-8 gap-1.5" onPaste={handlePaste}>
              {otp.map((digit, index) => (
                <Input
                  key={index}
                  id={`verify-otp-input-${index}`}
                  ref={(el) => { inputRefs.current[index] = el; }}
                  type="text"
                  inputMode="numeric"
                  maxLength={1}
                  value={digit}
                  onChange={(e) => handleOtpChange(index, e.target.value)}
                  onKeyDown={(e) => handleKeyDown(index, e)}
                  className="!w-full h-12 !px-0 text-center text-xl font-mono bg-white border border-[#C5C3BF] rounded-lg focus:border-[#111111] focus:ring-1 focus:ring-[#111111]"
                  disabled={isLoading || success}
                />
              ))}
            </div>
          </div>

          <Button
            id="verify-submit-btn"
            type="submit"
            className="w-full h-12 bg-[#111111] text-white hover:bg-[#111111]/90 rounded-full text-base font-medium"
            disabled={isLoading || success || otp.join("").length !== 8 || !email.trim()}
          >
            {isLoading ? (
              <>
                <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                Verifying...
              </>
            ) : (
              "Verify"
            )}
          </Button>
        </form>
      </div>

      <div id="verify-actions" className="mt-6 text-center">
        <p id="verify-login-link" className="text-sm text-[#555555]">
          Already have an account?{" "}
          <Link href="/login" className="text-primary hover:underline">
            Sign in
          </Link>
        </p>
        <p id="verify-help-text" className="mt-4 text-sm text-[#555555]">
          Need a new code? Contact your administrator.
        </p>
      </div>
    </div>
  );
}

export default function VerifyPage() {
  return (
    <div id="verify-page" className="min-h-screen bg-[#FAF9F7]">
      <Header variant="light" />
      <main id="verify-content" className="pt-24 flex items-center justify-center min-h-[calc(100vh-5rem)] px-6">
        <Suspense fallback={
          <div className="flex items-center justify-center">
            <Loader2 className="w-8 h-8 animate-spin text-primary" />
          </div>
        }>
          <VerifyForm />
        </Suspense>
      </main>
    </div>
  );
}
