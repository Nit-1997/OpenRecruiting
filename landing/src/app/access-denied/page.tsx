"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { Header } from "@/components/ui/header";
import { Footer } from "@/components/ui/footer";
import { Button } from "@/components/ui/button";
import { useAnalytics } from "@/hooks/useAnalytics";

export default function AccessDeniedPage() {
  const { trackEvent } = useAnalytics();

  useEffect(() => {
    trackEvent("signup_blocked_shown");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div id="access-denied-page" className="min-h-screen bg-[#FAF9F7] landing-page flex flex-col">
      <Header variant="light" />
      <main id="access-denied-main" className="flex-1 flex items-center justify-center px-4 pt-24 pb-12">
        <div id="access-denied-card" className="max-w-lg w-full text-center">
          <h1 id="access-denied-title" className="font-display text-3xl md:text-4xl font-normal text-[#111111] mb-4">
            Sign-up is invite-only
          </h1>
          <p id="access-denied-message" className="text-base text-[#111111]/70 leading-relaxed mb-8">
            OpenRecruiting is currently available to teams onboarded directly. If you need access, ask your administrator to invite you.
          </p>
          <div id="access-denied-actions" className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link
              id="access-denied-back-to-login-link"
              href="/login"
              className="text-sm text-[#111111]/60 hover:text-[#111111] underline-offset-4 hover:underline"
            >
              Back to login
            </Link>
          </div>
        </div>
      </main>
      <Footer />
    </div>
  );
}
