"use client";

import { useState } from "react";
import { MoveRight } from "lucide-react";
import { ParticleButton } from "@/components/ui/particle-button";
import { useAnalytics } from "@/hooks/useAnalytics";
import dynamic from "next/dynamic";

const CalendlyModal = dynamic(
  () => import("@/components/ui/calendly-modal").then((mod) => ({ default: mod.CalendlyModal })),
  { ssr: false },
);

function Hero() {
  const [isCalendlyOpen, setIsCalendlyOpen] = useState(false);
  const { trackEvent } = useAnalytics();

  return (
    <div id="hero-section" className="relative w-full h-screen overflow-hidden">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        id="hero-bg-layer"
        src="/hero-bg-5.png"
        alt=""
        className="absolute inset-0 z-0 w-full h-full object-cover"
      />

      <div id="hero-content-overlay" className="relative z-10 flex flex-col items-center justify-center h-full px-8 md:px-16 lg:px-24">
        <div id="hero-content-inner" className="max-w-4xl text-center">
          <h1
            id="hero-title"
            className="font-display text-5xl sm:text-6xl md:text-7xl lg:text-[72px] font-light text-[#111111] leading-[1.1] mb-6 animate-hero-fade-up-1"
          >
            Every interview produces a decision,{" "}
            <span className="italic">not</span> a debate.
          </h1>

          <p
            id="hero-subtitle"
            className="text-lg md:text-xl text-[#111111]/70 max-w-2xl mx-auto mb-10 animate-hero-fade-up-2"
          >
            Your interviewers forget. Your recruiters chase. OpenRecruiting captures structured feedback in real time so nobody has to.
          </p>

          <div id="hero-cta-group" className="animate-hero-fade-up-3">
            <ParticleButton
              id="hero-cta-primary"
              particleClassName="bg-[#111111]"
              className="h-12 md:h-14 px-8 md:px-10 text-base md:text-lg rounded-full bg-[#111111] text-white hover:bg-[#111111]/90 gap-3 transition-colors"
              onClick={() => { trackEvent("demo_booking_opened", { cta_location: "hero" }); setIsCalendlyOpen(true); }}
            >
              Book Demo <MoveRight className="w-5 h-5" />
            </ParticleButton>
          </div>
        </div>
      </div>

      {isCalendlyOpen && <CalendlyModal isOpen={isCalendlyOpen} onClose={() => setIsCalendlyOpen(false)} />}

      {/* Bottom notch - scroll hint */}
      <div className="absolute bottom-0 left-0 right-0 z-10 flex justify-center">
        <div className="bg-[#FAF9F7] w-[320px] md:w-[400px] h-10 rounded-t-[2rem] flex items-center justify-center shadow-[0_-4px_20px_rgba(0,0,0,0.05)]">
          <div className="w-12 h-1 bg-[#111111]/15 rounded-full" />
        </div>
      </div>
    </div>
  );
}

export { Hero };
