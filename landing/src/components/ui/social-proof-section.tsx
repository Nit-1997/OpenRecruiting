"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { AnimatedTestimonials } from "@/components/ui/animated-testimonials";
import {
  FileText,
  ClipboardCheck,
  Bot,
  PenLine,
  FileCheck,
  BarChart3,
} from "lucide-react";

const steps = [
  {
    id: "sp-step-interview-plan",
    step: 1,
    icon: FileText,
    title: "Generate Interview Plan",
    description:
      "AI creates a structured interview plan based on competition analysis and industry best practices.",
  },
  {
    id: "sp-step-scorecards",
    step: 2,
    icon: ClipboardCheck,
    title: "Get Score-Cards",
    description:
      "Receive customized score-cards for each interview round to ensure consistent evaluation.",
  },
  {
    id: "sp-step-ai-joins",
    step: 3,
    icon: Bot,
    title: "AI Joins Interview",
    description:
      "Our AI assistant joins your interviews to listen, transcribe, and capture key moments.",
  },
  {
    id: "sp-step-auto-feedback",
    step: 4,
    icon: PenLine,
    title: "Auto-Fill Feedback",
    description:
      "AI automatically fills feedback in real-time during and after the interview.",
  },
  {
    id: "sp-step-interview-packet",
    step: 5,
    icon: FileCheck,
    title: "Interview Packet Created",
    description:
      "Get a comprehensive final interview packet with all feedback and insights compiled.",
  },
  {
    id: "sp-step-data-visibility",
    step: 6,
    icon: BarChart3,
    title: "Data & Visibility",
    description:
      "Gain full visibility into your interviews with actionable data and analytics.",
  },
];

const testimonials = [
  {
    quote:
      "OpenRecruiting is the first product that made me feel like I finally had a real co-pilot for hiring, not just another tracker. Every interview was scored against the same competency framework, so by the time we got to the final round, the signal was clear. We weren't debating opinions in a debrief room — we were looking at consistent, evidence-backed assessments. If you're a hiring manager who cares about raising the quality of your hiring decisions without adding more process overhead, OpenRecruiting is your unfair advantage.",
    name: "Priya Raman",
    designation: "Senior Product Leader @ Northwind",
    src: "/testimonials/nachi.png",
  },
  {
    quote:
      "OpenRecruiting is such a clean and well thought execution for a real pain point. OpenRecruiting actually joins the interview, and by the time the call wraps up, structured feedback is already there. Every interviewer, every round, scored in a consistent way. No more chasing people for notes. No more trying to remember what someone said three days ago. Just clear, usable data that helps the hiring team make better decisions.",
    name: "Marcus Lee",
    designation: "Engineering Leader @ Vertex Legal",
    src: "/testimonials/vidit.png",
    isCustomer: false,
  },
];

function HowItWorksStack() {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  return (
    <>
      <div
        id="sp-steps-stack-container"
        className="hidden md:block relative"
        style={{ perspective: "1200px" }}
      >
        <div
          id="sp-steps-stack"
          className="relative w-full"
          style={{ height: `${steps.length * 56 + 80}px` }}
        >
          {steps.map((step, index) => {
            const isHovered = hoveredIndex === index;
            const offset = hoveredIndex !== null && index > hoveredIndex ? 20 : 0;

            return (
              <motion.div
                key={step.id}
                id={step.id}
                className="absolute left-0 right-0 bg-[var(--lp-surface)] border border-[var(--lp-border)] rounded-xl p-5 transition-all duration-500 ease-out"
                style={{
                  top: `${index * 56}px`,
                  zIndex: isHovered ? 20 : steps.length - index,
                  transform: `translateY(${offset}px) scale(${isHovered ? 1 : 1 - index * 0.01})`,
                  boxShadow: isHovered ? "0 8px 30px rgba(0,0,0,0.08)" : "none",
                }}
                onMouseEnter={() => setHoveredIndex(index)}
                onMouseLeave={() => setHoveredIndex(null)}
                initial={{ opacity: 0, y: 40 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-40px" }}
                transition={{ duration: 0.4, delay: index * 0.08 }}
              >
                <div className="flex items-start gap-4">
                  <span
                    id={`${step.id}-badge`}
                    className="font-mono-label text-xs px-2.5 py-1 rounded-full bg-[var(--lp-surface-accent)] text-[var(--lp-text-faint)] border border-[var(--lp-border)] flex-shrink-0"
                  >
                    {String(step.step).padStart(2, "0")}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 mb-1.5">
                      <step.icon className="w-4 h-4 text-[var(--lp-text-muted)] flex-shrink-0" />
                      <h3
                        id={`${step.id}-title`}
                        className="font-display text-base font-medium text-[var(--lp-text-primary)]"
                      >
                        {step.title}
                      </h3>
                    </div>
                    <p
                      id={`${step.id}-description`}
                      className={`text-sm text-[var(--lp-text-secondary)] leading-relaxed transition-all duration-300 ${
                        isHovered ? "max-h-20 opacity-100" : "max-h-0 opacity-0 overflow-hidden"
                      }`}
                    >
                      {step.description}
                    </p>
                  </div>
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>

      <div id="sp-steps-mobile-fallback" className="md:hidden space-y-4">
        {steps.map((step) => (
          <div
            key={`mobile-${step.id}`}
            id={`mobile-${step.id}`}
            className="bg-[var(--lp-surface)] border border-[var(--lp-border)] rounded-xl p-5"
          >
            <div className="flex items-start gap-3">
              <span className="font-mono-label text-xs px-2 py-1 rounded-full bg-[var(--lp-surface-accent)] text-[var(--lp-text-faint)] border border-[var(--lp-border)]">
                {String(step.step).padStart(2, "0")}
              </span>
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <step.icon className="w-4 h-4 text-[var(--lp-text-muted)]" />
                  <h3 className="font-display text-base font-medium text-[var(--lp-text-primary)]">
                    {step.title}
                  </h3>
                </div>
                <p className="text-sm text-[var(--lp-text-secondary)] leading-relaxed">
                  {step.description}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

function SocialProofSection() {
  return (
    <section id="social-proof-section" className="py-16 md:py-20 bg-[var(--lp-bg)]">
      <div id="social-proof-inner" className="max-w-[1100px] mx-auto px-6">
        <motion.div
          id="social-proof-testimonials"
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6 }}
        >
          <h2
            id="sp-testimonials-title"
            className="font-display text-3xl md:text-4xl font-light text-[var(--lp-text-primary)] mb-8 text-center"
          >
Loved by hiring teams
          </h2>

          <AnimatedTestimonials testimonials={testimonials} autoplay />
        </motion.div>
      </div>
    </section>
  );
}

export { SocialProofSection };
