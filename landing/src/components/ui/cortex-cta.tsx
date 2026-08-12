"use client";

import { motion } from "framer-motion";
import { MoveRight } from "lucide-react";
import Link from "next/link";
import { ParticleButton } from "@/components/ui/particle-button";
import { useAnalytics } from "@/hooks/useAnalytics";

const QUOTE_LINES = [
  { text: "AI agents without context are empty.", emphasis: false },
  { text: "Fast, but blind.", emphasis: false },
  { text: "Cortex is what makes them worth trusting.", emphasis: true },
];

function CortexQuoteBand() {
  return (
    <section id="cortex-quote-section" className="relative py-24 md:py-36 overflow-hidden bg-[#0A0A0A]">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        id="cortex-quote-bg"
        src="/cortex-bg-3.jpg"
        alt=""
        className="absolute inset-0 w-full h-full object-cover opacity-60 z-0"
      />
      <div
        id="cortex-quote-overlay"
        className="absolute inset-0 bg-gradient-to-b from-[#0A0A0A]/80 via-[#0A0A0A]/40 to-[#0A0A0A]/80 z-0 pointer-events-none"
      />

      <div id="cortex-quote-inner" className="relative z-10 max-w-[900px] mx-auto px-6 text-center">
        <motion.p
          id="cortex-quote-eyebrow"
          className="font-mono-label text-[11px] tracking-[0.3em] uppercase text-white/45 mb-8"
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.6 }}
        >
          Why it matters
        </motion.p>
        {QUOTE_LINES.map((line, i) => (
          <motion.p
            key={line.text}
            id={`cortex-quote-line-${i}`}
            initial={{ opacity: 0, y: 24 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-100px" }}
            transition={{ duration: 0.6, delay: i * 0.25 }}
            className={
              line.emphasis
                ? "font-display text-4xl md:text-6xl font-light italic text-white leading-tight mt-6"
                : "font-display text-3xl md:text-5xl font-light text-white/55 leading-tight"
            }
          >
            {line.text}
          </motion.p>
        ))}
      </div>
    </section>
  );
}

function CortexCTA() {
  const { trackEvent } = useAnalytics();

  return (
    <section id="cortex-cta-section" className="relative py-24 md:py-32 overflow-hidden bg-[#0A0A0A]">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        id="cortex-cta-bg"
        src="/cortex-bg-2.jpg"
        alt=""
        className="absolute inset-0 w-full h-full object-cover z-0"
      />
      <div
        id="cortex-cta-overlay"
        className="absolute inset-0 bg-gradient-to-b from-black/55 via-black/45 to-black/60 z-0 pointer-events-none"
      />

      <div id="cortex-cta-inner" className="relative z-10 max-w-[960px] mx-auto px-6">
        <motion.div
          id="cortex-cta-content"
          className="text-center"
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.6 }}
        >
          <h2
            id="cortex-cta-title"
            className="font-display text-4xl md:text-6xl font-light text-white mb-5"
          >
            Stop guessing. Start knowing.
          </h2>
          <p
            id="cortex-cta-description"
            className="text-base md:text-lg text-white/70 max-w-xl mx-auto mb-10"
          >
            See what Cortex can learn from the interviews you’re already running. A 30-minute
            walkthrough with your hiring data in mind.
          </p>
          <div id="cortex-cta-buttons" className="flex flex-col sm:flex-row items-center justify-center gap-4 sm:gap-6">
            <Link href="/login" id="cortex-cta-get-started-link">
              <ParticleButton
                id="cortex-cta-get-started-btn"
                particleClassName="bg-white"
                className="h-12 md:h-14 px-8 md:px-10 text-base md:text-lg rounded-full bg-white text-[#111111] hover:bg-white/90 gap-3 transition-colors"
                onClick={() =>
                  trackEvent("cta_clicked", { cta: "get_started", cta_location: "cortex_cta" })
                }
              >
                Get started <MoveRight className="w-5 h-5" />
              </ParticleButton>
            </Link>
            <Link
              id="cortex-cta-recruiter-link"
              href="/"
              className="text-sm md:text-base text-white/70 hover:text-white transition-colors underline underline-offset-4 decoration-white/30 hover:decoration-white"
            >
              Explore OpenRecruiting for recruiters
            </Link>
          </div>
        </motion.div>
      </div>

    </section>
  );
}

export { CortexQuoteBand, CortexCTA };
