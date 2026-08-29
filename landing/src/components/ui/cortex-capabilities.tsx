"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import {
  MessageCircleQuestion,
  GitCompareArrows,
  Gauge,
  Lightbulb,
  Search,
  Sparkles,
  TriangleAlert,
  CheckCircle2,
} from "lucide-react";

type CapabilityId = "ask" | "debrief" | "calibration" | "memory";

const ASK_QUESTION = "Which sourcing channel gives us our strongest engineering hires?";

const ASK_EVIDENCE = [
  "Referral pass-through to onsite: 38% vs 16% for outbound",
  "Average onsite score 4.2 / 5 vs 3.4 across other channels",
  "Sample: 214 candidates across 9 engineering requisitions",
];

function AskAnythingDemo({ animate }: { animate: boolean }) {
  const [typedChars, setTypedChars] = useState(animate ? 0 : ASK_QUESTION.length);
  const [phase, setPhase] = useState(animate ? 0 : 2); // 0 typing, 1 thinking, 2 answer

  useEffect(() => {
    if (!animate) return;
    if (phase === 0) {
      if (typedChars < ASK_QUESTION.length) {
        const timer = setTimeout(() => setTypedChars((c) => c + 2), 32);
        return () => clearTimeout(timer);
      }
      const timer = setTimeout(() => setPhase(1), 250);
      return () => clearTimeout(timer);
    }
    if (phase === 1) {
      const timer = setTimeout(() => setPhase(2), 900);
      return () => clearTimeout(timer);
    }
  }, [animate, phase, typedChars]);

  return (
    <div id="cortex-cap-ask-demo" className="h-full flex flex-col gap-3">
      <div
        id="cortex-cap-ask-input"
        className="flex items-center gap-2.5 bg-white border border-[#E5E3DF] rounded-xl px-4 py-3"
      >
        <Search className="w-4 h-4 text-[#737373] flex-shrink-0" />
        <p className="text-sm text-[#111111] leading-snug">
          {ASK_QUESTION.slice(0, typedChars)}
          {phase === 0 && <span id="cortex-cap-ask-caret" className="inline-block w-px h-4 bg-[#111111] align-middle ml-0.5 animate-pulse" />}
        </p>
      </div>

      {phase === 1 && (
        <motion.div
          id="cortex-cap-ask-thinking"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex items-center gap-2 px-1"
        >
          <Sparkles className="w-3.5 h-3.5 text-[#737373]" />
          <span className="text-xs text-[#737373]">Cortex is reading the graph…</span>
        </motion.div>
      )}

      {phase === 2 && (
        <motion.div
          id="cortex-cap-ask-answer"
          initial={animate ? { opacity: 0, y: 10 } : false}
          animate={{ opacity: 1, y: 0 }}
          className="bg-white border border-[#E5E3DF] rounded-xl p-4"
        >
          <p id="cortex-cap-ask-answer-headline" className="text-sm font-semibold text-[#111111] mb-3">
            Referrals — candidates are 2.4× more likely to reach offer.
          </p>
          <div id="cortex-cap-ask-evidence" className="space-y-2">
            {ASK_EVIDENCE.map((item, i) => (
              <motion.div
                key={item}
                id={`cortex-cap-ask-evidence-${i}`}
                initial={animate ? { opacity: 0, x: -10 } : false}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: animate ? 0.3 + i * 0.35 : 0 }}
                className="flex items-start gap-2"
              >
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 mt-0.5 flex-shrink-0" />
                <span className="text-xs text-[#555555] leading-relaxed">{item}</span>
              </motion.div>
            ))}
          </div>
        </motion.div>
      )}
    </div>
  );
}

const DEBRIEF_ROWS = [
  { competency: "Systems depth", a: { label: "Strong", tone: "good" }, b: { label: "Mixed", tone: "warn" } },
  { competency: "Trade-off reasoning", a: { label: "Strong", tone: "good" }, b: { label: "Strong", tone: "good" } },
  { competency: "Communication", a: { label: "Solid", tone: "good" }, b: { label: "Solid", tone: "good" } },
];

const toneClass = (tone: string) =>
  tone === "good" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700";

function DebriefDemo({ animate }: { animate: boolean }) {
  return (
    <div id="cortex-cap-debrief-demo" className="h-full flex flex-col gap-3">
      <div
        id="cortex-cap-debrief-card"
        className="bg-white border border-[#E5E3DF] rounded-xl p-4 flex-1"
      >
        <div id="cortex-cap-debrief-head" className="flex items-center justify-between mb-3">
          <p className="text-sm font-semibold text-[#111111]">Backend Engineer — final debrief</p>
          <span className="font-mono-label text-[9px] tracking-[0.2em] uppercase text-[#737373]">
            2 finalists
          </span>
        </div>
        <div
          id="cortex-cap-debrief-grid-head"
          className="grid grid-cols-[1.4fr_1fr_1fr] gap-2 pb-2 border-b border-[#E5E3DF]"
        >
          <span className="text-[10px] uppercase tracking-wide text-[#737373]">Competency</span>
          <span className="text-[10px] font-semibold text-[#111111] text-center">A. Verma</span>
          <span className="text-[10px] font-semibold text-[#111111] text-center">J. Doe</span>
        </div>
        {DEBRIEF_ROWS.map((row, i) => (
          <motion.div
            key={row.competency}
            id={`cortex-cap-debrief-row-${i}`}
            initial={animate ? { opacity: 0, y: 8 } : false}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: animate ? 0.2 + i * 0.3 : 0 }}
            className="grid grid-cols-[1.4fr_1fr_1fr] gap-2 items-center py-2.5 border-b border-[#F2F0ED] last:border-0"
          >
            <span className="text-xs text-[#111111]">{row.competency}</span>
            <span className={`justify-self-center px-2 py-0.5 rounded-full text-[10px] font-medium ${toneClass(row.a.tone)}`}>
              {row.a.label}
            </span>
            <span className={`justify-self-center px-2 py-0.5 rounded-full text-[10px] font-medium ${toneClass(row.b.tone)}`}>
              {row.b.label}
            </span>
          </motion.div>
        ))}
        <motion.p
          id="cortex-cap-debrief-quote"
          initial={animate ? { opacity: 0 } : false}
          animate={{ opacity: 1 }}
          transition={{ delay: animate ? 1.3 : 0 }}
          className="text-[11px] italic text-[#737373] leading-relaxed mt-3"
        >
          “Walked through cache invalidation under partial failure unprompted — strongest answer
          we’ve recorded on this question.” — R3 transcript, A. Verma
        </motion.p>
      </div>
      <motion.div
        id="cortex-cap-debrief-recommendation"
        initial={animate ? { opacity: 0, y: 10 } : false}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: animate ? 1.7 : 0 }}
        className="flex items-center gap-2.5 bg-[#111111] text-white rounded-xl px-4 py-3"
      >
        <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
        <p className="text-xs leading-snug">
          <span className="font-semibold">Cortex recommends A. Verma</span> — stronger evidence on
          systems depth, consistent across all three panels.
        </p>
      </motion.div>
    </div>
  );
}

const CALIBRATION_ROWS = [
  { name: "Sarah Parker", score: 92, drift: false },
  { name: "Dev Patel", score: 88, drift: false },
  { name: "Sloane Nair", score: 85, drift: false },
  { name: "Mike Ross", score: 71, drift: true },
];

function CalibrationDemo({ animate }: { animate: boolean }) {
  return (
    <div id="cortex-cap-calibration-demo" className="h-full flex flex-col gap-3">
      <div id="cortex-cap-calibration-card" className="bg-white border border-[#E5E3DF] rounded-xl p-4">
        <div className="flex items-center justify-between mb-4">
          <p className="text-sm font-semibold text-[#111111]">Interviewer signal consistency</p>
          <span className="font-mono-label text-[9px] tracking-[0.2em] uppercase text-[#737373]">
            Last 90 days
          </span>
        </div>
        <div id="cortex-cap-calibration-rows" className="space-y-3.5">
          {CALIBRATION_ROWS.map((row, i) => (
            <div key={row.name} id={`cortex-cap-calibration-row-${i}`}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-[#111111]">{row.name}</span>
                <span className="flex items-center gap-2">
                  {row.drift && (
                    <motion.span
                      id="cortex-cap-calibration-drift-chip"
                      initial={animate ? { opacity: 0, scale: 0.85 } : false}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ delay: animate ? 1.6 : 0 }}
                      className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 text-[9px] font-medium"
                    >
                      <TriangleAlert className="w-2.5 h-2.5" /> drifting
                    </motion.span>
                  )}
                  <span className="text-xs font-medium text-[#555555]">{row.score}%</span>
                </span>
              </div>
              <div className="h-1.5 rounded-full bg-[#F2F0ED] overflow-hidden">
                <motion.div
                  id={`cortex-cap-calibration-bar-${i}`}
                  initial={animate ? { width: 0 } : { width: `${row.score}%` }}
                  animate={{ width: `${row.score}%` }}
                  transition={{ delay: animate ? 0.2 + i * 0.18 : 0, duration: 0.7, ease: "easeOut" }}
                  className={`h-full rounded-full ${row.drift ? "bg-amber-400" : "bg-[#111111]"}`}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
      <motion.p
        id="cortex-cap-calibration-note"
        initial={animate ? { opacity: 0 } : false}
        animate={{ opacity: 1 }}
        transition={{ delay: animate ? 2 : 0 }}
        className="text-xs text-[#555555] leading-relaxed px-1"
      >
        Mike’s ratings drifted 1.2 points below the panel average in the last 30 days. Cortex
        flagged the drift before it cost a strong candidate.
      </motion.p>
    </div>
  );
}

const MEMORY_PATTERNS = [
  {
    text: "Candidates who quantify trade-offs in systems design are 3.1× more likely to become top performers.",
    meta: "Pattern across 12 hires · 2 years of outcomes",
  },
  {
    text: "Take-home completion speed has no correlation with onsite performance.",
    meta: "97 candidates · correlation r = 0.04",
  },
  {
    text: "Your bar for “communication” has tightened 18% since January.",
    meta: "Drift measured across 6 interviewers",
  },
];

function MemoryDemo({ animate }: { animate: boolean }) {
  return (
    <div id="cortex-cap-memory-demo" className="h-full flex flex-col justify-center gap-3">
      {MEMORY_PATTERNS.map((pattern, i) => (
        <motion.div
          key={pattern.meta}
          id={`cortex-cap-memory-pattern-${i}`}
          initial={animate ? { opacity: 0, y: 14 } : false}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: animate ? 0.25 + i * 0.5 : 0, duration: 0.45 }}
          className="flex items-start gap-3 bg-white border border-[#E5E3DF] rounded-xl px-4 py-3.5"
        >
          <span className="w-6 h-6 rounded-full bg-[#111111] flex items-center justify-center flex-shrink-0 mt-0.5">
            <Sparkles className="w-3 h-3 text-white" />
          </span>
          <div>
            <p className="text-xs text-[#111111] leading-relaxed">{pattern.text}</p>
            <p className="font-mono-label text-[9px] tracking-[0.15em] uppercase text-[#737373] mt-1.5">
              {pattern.meta}
            </p>
          </div>
        </motion.div>
      ))}
    </div>
  );
}

const CAPABILITIES = [
  {
    id: "ask" as CapabilityId,
    label: "Ask anything",
    icon: MessageCircleQuestion,
    description: "Plain-English questions over your whole hiring history — answered with evidence.",
    duration: 7000,
    Demo: AskAnythingDemo,
  },
  {
    id: "debrief" as CapabilityId,
    label: "Debriefs with receipts",
    icon: GitCompareArrows,
    description: "Side-by-side finalists, competency by competency, with transcript-level proof.",
    duration: 6500,
    Demo: DebriefDemo,
  },
  {
    id: "calibration" as CapabilityId,
    label: "Calibration & drift",
    icon: Gauge,
    description: "See who rates how — and catch rubric drift before it costs you a hire.",
    duration: 6000,
    Demo: CalibrationDemo,
  },
  {
    id: "memory" as CapabilityId,
    label: "Institutional memory",
    icon: Lightbulb,
    description: "The patterns your best people sense but can’t name — surfaced and proven.",
    duration: 6000,
    Demo: MemoryDemo,
  },
];

function CortexCapabilities() {
  const [activeId, setActiveId] = useState<CapabilityId>("ask");
  const [isAutoPlaying, setIsAutoPlaying] = useState(true);
  const prefersReducedMotion = useReducedMotion();
  const animate = !prefersReducedMotion;

  const activeIndex = CAPABILITIES.findIndex((c) => c.id === activeId);
  const active = CAPABILITIES[activeIndex];

  useEffect(() => {
    if (!isAutoPlaying || !animate) return;
    const timer = setTimeout(() => {
      setActiveId(CAPABILITIES[(activeIndex + 1) % CAPABILITIES.length].id);
    }, active.duration);
    return () => clearTimeout(timer);
  }, [isAutoPlaying, animate, activeIndex, active.duration]);

  return (
    <section id="cortex-capabilities-section" className="py-20 md:py-28 bg-[var(--lp-bg)]">
      <div id="cortex-capabilities-inner" className="max-w-[1100px] mx-auto px-6">
        <p
          id="cortex-capabilities-eyebrow"
          className="font-mono-label text-xs tracking-[0.2em] uppercase text-[var(--lp-text-muted)] text-center mb-4"
        >
          What it unlocks
        </p>
        <h2
          id="cortex-capabilities-title"
          className="font-display text-4xl md:text-5xl font-light text-[var(--lp-text-primary)] text-center mb-5"
        >
          Built for the people who own the hiring bar
        </h2>
        <p
          id="cortex-capabilities-subtitle"
          className="text-base md:text-lg text-[var(--lp-text-secondary)] text-center max-w-2xl mx-auto mb-12"
        >
          Cortex turns scattered interview exhaust into command-room intelligence for TA leaders
          and the agents that work for them.
        </p>

        <div
          id="cortex-capabilities-panel"
          className="rounded-3xl border border-[var(--lp-border)] bg-white/70 p-5 md:p-8"
        >
          <div
            id="cortex-capabilities-grid"
            className="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-5 lg:gap-8"
          >
            {/* Tab rail */}
            <div
              id="cortex-capabilities-tabs"
              className="flex flex-row lg:flex-col gap-2 overflow-x-auto lg:overflow-visible pb-2 lg:pb-0"
            >
              {CAPABILITIES.map((capability) => {
                const Icon = capability.icon;
                const isActive = capability.id === activeId;
                return (
                  <button
                    key={capability.id}
                    id={`cortex-capabilities-tab-${capability.id}`}
                    type="button"
                    onClick={() => {
                      setActiveId(capability.id);
                      setIsAutoPlaying(false);
                    }}
                    className={`relative flex items-center gap-3 px-4 py-3 rounded-xl text-left transition-all duration-300 flex-shrink-0 cursor-pointer overflow-hidden ${
                      isActive
                        ? "bg-[#111111] text-white shadow-lg"
                        : "bg-[var(--lp-surface)] text-[var(--lp-text-secondary)] hover:bg-white border border-[var(--lp-border)]"
                    }`}
                  >
                    <span
                      className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
                        isActive ? "bg-white/15" : "bg-[var(--lp-surface-accent)]"
                      }`}
                    >
                      <Icon className="w-4 h-4" />
                    </span>
                    <span className="min-w-0 hidden lg:block">
                      <span className={`block text-sm font-medium truncate ${isActive ? "text-white" : ""}`}>
                        {capability.label}
                      </span>
                      {isActive && (
                        <span className="block text-[11px] opacity-70 mt-0.5 line-clamp-2">
                          {capability.description}
                        </span>
                      )}
                    </span>
                    <span className="lg:hidden text-xs font-medium whitespace-nowrap">
                      {capability.label}
                    </span>
                    {isActive && isAutoPlaying && animate && (
                      <motion.span
                        key={activeId}
                        id="cortex-capabilities-tab-progress"
                        className="absolute bottom-0 left-0 h-0.5 bg-white/40"
                        initial={{ width: "0%" }}
                        animate={{ width: "100%" }}
                        transition={{ duration: active.duration / 1000, ease: "linear" }}
                      />
                    )}
                  </button>
                );
              })}
            </div>

            {/* Demo panel */}
            <div
              id="cortex-capabilities-stage"
              className="h-[420px] md:h-[440px] rounded-2xl bg-[var(--lp-surface)] border border-[var(--lp-border)] p-4 md:p-6 overflow-hidden"
            >
              <AnimatePresence mode="wait">
                <motion.div
                  key={activeId}
                  id={`cortex-capabilities-demo-${activeId}`}
                  initial={{ opacity: 0, x: 30 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -30 }}
                  transition={{ duration: 0.3 }}
                  className="h-full"
                >
                  <active.Demo animate={animate} />
                </motion.div>
              </AnimatePresence>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

export { CortexCapabilities };
