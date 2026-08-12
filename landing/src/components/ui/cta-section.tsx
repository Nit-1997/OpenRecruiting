"use client";

import { motion } from "framer-motion";
import { MoveRight } from "lucide-react";
import Link from "next/link";
import { ParticleButton } from "@/components/ui/particle-button";
import { useAnalytics } from "@/hooks/useAnalytics";

function CTASection() {
  const { trackEvent } = useAnalytics();

  return (
    <section
      id="cta-section"
      className="py-20 md:py-28 relative overflow-hidden"
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/Ending.png"
        alt=""
        className="absolute inset-0 w-full h-full object-cover z-0"
      />

      <div id="cta-inner" className="max-w-[960px] mx-auto px-6 relative z-10">
        <motion.div
          id="cta-content"
          className="text-center"
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.6 }}
        >
          <h2
            id="cta-title"
            className="font-display text-4xl md:text-5xl font-light text-white mb-5"
          >
            What if your next debrief took 5 minutes
            <br />
            instead of 5 days?
          </h2>

          <p id="cta-description" className="text-base md:text-lg text-white/70 max-w-xl mx-auto mb-10">
            See how OpenRecruiting works with your ATS and your video calls. Nothing to install. Nothing changes for your interviewers.
          </p>

          <div id="cta-buttons" className="flex justify-center">
            <Link href="/login" id="cta-get-started-link">
            <ParticleButton
              id="cta-get-started-btn"
              particleClassName="bg-white"
              className="h-12 md:h-14 px-8 md:px-10 text-base md:text-lg rounded-full bg-white text-[#111111] hover:bg-white/90 gap-3"
              onClick={() => trackEvent("cta_clicked", { cta: "get_started", cta_location: "cta_section" })}
            >
              Get started <MoveRight className="w-5 h-5" />
            </ParticleButton>
            </Link>
          </div>
        </motion.div>
      </div>
    </section>
  );
}

export { CTASection };
