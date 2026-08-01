"use client";

import { useState } from "react";
import { MoveRight } from "lucide-react";
import { motion } from "framer-motion";
import { ParticleButton } from "@/components/ui/particle-button";
import { useAnalytics } from "@/hooks/useAnalytics";
import dynamic from "next/dynamic";

const CalendlyModal = dynamic(
  () => import("@/components/ui/calendly-modal").then((mod) => ({ default: mod.CalendlyModal })),
  { ssr: false },
);

function CortexHero() {
  const [isCalendlyOpen, setIsCalendlyOpen] = useState(false);
  const { trackEvent } = useAnalytics();

  return (
    <>
      <div
        id="cortex-hero-viewport"
        className="relative h-screen w-full flex items-center justify-center px-8 md:px-16 lg:px-24 overflow-hidden bg-[#0A0A0A]"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          id="cortex-hero-bg-img"
          src="/cortex-bg.jpg"
          alt=""
          className="absolute inset-0 w-full h-full object-cover"
        />
        {/* Soft overlay so white text stays legible across the bright center */}
        <div
          id="cortex-hero-bg-overlay"
          className="absolute inset-0 bg-gradient-to-b from-black/40 via-black/50 to-black/45 pointer-events-none"
        />

        <div id="cortex-hero-content" className="relative z-10 max-w-4xl text-center">
          <p
            id="cortex-hero-eyebrow"
            className="font-mono-label text-[11px] md:text-xs tracking-[0.3em] uppercase text-white/60 mb-6 animate-hero-fade-up-1"
          >
            The intelligence layer for hiring
          </p>

          <h1
            id="cortex-hero-title"
            className="font-display text-5xl sm:text-6xl md:text-7xl lg:text-[80px] font-light text-white leading-[1.1] mb-6 animate-hero-fade-up-1"
          >
            OpenRecruiting Cortex
          </h1>

          <p
            id="cortex-hero-subtitle"
            className="text-lg md:text-xl text-white/70 max-w-2xl mx-auto mb-10 animate-hero-fade-up-2"
          >
            Your hiring decisions are only as good as the intelligence behind them.
          </p>

          <div id="cortex-hero-cta-wrap" className="animate-hero-fade-up-3">
            <ParticleButton
              id="cortex-hero-book-demo-btn"
              particleClassName="bg-white"
              className="h-12 md:h-14 px-8 md:px-10 text-base md:text-lg rounded-full bg-white text-[#111111] hover:bg-white/90 gap-3 transition-colors"
              onClick={() => {
                trackEvent("demo_booking_opened", { cta_location: "cortex_hero" });
                setIsCalendlyOpen(true);
              }}
            >
              Book Demo <MoveRight className="w-5 h-5" />
            </ParticleButton>
          </div>
        </div>

        {/* Scroll cue so the story below doesn't get missed */}
        <div
          id="cortex-hero-scroll-cue"
          className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10 flex flex-col items-center gap-3 animate-hero-fade-up-35"
        >
          <span
            id="cortex-hero-scroll-cue-label"
            className="font-mono-label text-[10px] tracking-[0.25em] uppercase text-white/45"
          >
            Scroll
          </span>
          <span
            id="cortex-hero-scroll-cue-track"
            className="relative block w-px h-10 overflow-hidden bg-white/15"
          >
            <motion.span
              id="cortex-hero-scroll-cue-dot"
              className="absolute left-0 top-0 w-px h-3 bg-white/80"
              animate={{ y: [0, 40] }}
              transition={{ duration: 1.6, repeat: Infinity, ease: "easeIn" }}
            />
          </span>
        </div>
      </div>

      {isCalendlyOpen && (
        <CalendlyModal isOpen={isCalendlyOpen} onClose={() => setIsCalendlyOpen(false)} />
      )}
    </>
  );
}

export { CortexHero };
