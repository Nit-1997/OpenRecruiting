"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import { Mic, ClipboardCheck, CheckCircle2, PhoneCall, Search } from "lucide-react";

const CAPTURE_EVENTS = [
  { icon: Mic, text: "Interview completed", meta: "Sr. Backend Engineer · R2" },
  { icon: ClipboardCheck, text: "Scorecard submitted", meta: "Sarah Parker · Strong Yes" },
  { icon: CheckCircle2, text: "Decision logged", meta: "John Doe · Hired" },
  { icon: PhoneCall, text: "Intake call captured", meta: "Product Designer · New role" },
  { icon: Mic, text: "Interview completed", meta: "Staff ML Engineer · Onsite" },
  { icon: ClipboardCheck, text: "Scorecard submitted", meta: "Dev Patel · Yes" },
];

function CaptureVisual({ animate }: { animate: boolean }) {
  const [tick, setTick] = useState(2);

  useEffect(() => {
    if (!animate) return;
    const interval = setInterval(() => setTick((t) => t + 1), 1800);
    return () => clearInterval(interval);
  }, [animate]);

  const visible = [tick, tick - 1, tick - 2].map(
    (t) => CAPTURE_EVENTS[((t % CAPTURE_EVENTS.length) + CAPTURE_EVENTS.length) % CAPTURE_EVENTS.length],
  );

  return (
    <div id="cortex-how-capture-visual" className="h-full flex flex-col justify-center gap-2 px-4">
      <AnimatePresence initial={false} mode="popLayout">
        {visible.map((event, i) => {
          const Icon = event.icon;
          return (
            <motion.div
              key={tick - i}
              id={`cortex-how-capture-event-${tick - i}`}
              layout
              initial={{ opacity: 0, y: -14 }}
              animate={{ opacity: i === 2 ? 0.45 : 1, y: 0 }}
              exit={{ opacity: 0, y: 14 }}
              transition={{ duration: 0.35 }}
              className="flex items-center gap-2.5 bg-white border border-[var(--lp-border)] rounded-lg px-3 py-2"
            >
              <Icon className="w-3.5 h-3.5 text-[#555555] flex-shrink-0" />
              <div className="min-w-0">
                <p className="text-[11px] font-medium text-[#111111] leading-tight truncate">{event.text}</p>
                <p className="text-[10px] text-[#737373] leading-tight truncate">{event.meta}</p>
              </div>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}

const MINI_NODES = [
  { x: 30, y: 88 },
  { x: 78, y: 26 },
  { x: 140, y: 64 },
  { x: 104, y: 122 },
  { x: 196, y: 110 },
  { x: 188, y: 32 },
];

const MINI_EDGES: Array<[number, number]> = [
  [0, 1],
  [1, 2],
  [2, 3],
  [0, 3],
  [2, 4],
  [2, 5],
  [4, 5],
];

function ConnectVisual({ animate }: { animate: boolean }) {
  const [stage, setStage] = useState(animate ? 0 : MINI_EDGES.length);
  const totalStages = MINI_EDGES.length + 3; // edges draw one by one, hold, reset

  useEffect(() => {
    if (!animate) return;
    const interval = setInterval(() => setStage((s) => (s + 1) % totalStages), 700);
    return () => clearInterval(interval);
  }, [animate, totalStages]);

  const drawnEdges = Math.min(stage, MINI_EDGES.length);
  const settled = stage >= MINI_EDGES.length;

  return (
    <div id="cortex-how-connect-visual" className="h-full flex items-center justify-center">
      <svg id="cortex-how-connect-svg" viewBox="0 0 224 148" className="w-full max-w-[224px] h-auto">
        {MINI_EDGES.slice(0, drawnEdges).map(([a, b], i) => (
          <motion.line
            key={`${a}-${b}`}
            id={`cortex-how-connect-edge-${a}-${b}`}
            x1={MINI_NODES[a].x}
            y1={MINI_NODES[a].y}
            x2={MINI_NODES[b].x}
            y2={MINI_NODES[b].y}
            stroke="#9A958E"
            strokeWidth={1.2}
            initial={{ pathLength: 0, opacity: 0 }}
            animate={{ pathLength: 1, opacity: 1 }}
            transition={{ duration: 0.5, delay: animate ? 0 : i * 0.05 }}
          />
        ))}
        {MINI_NODES.map((node, i) => (
          <motion.circle
            key={i}
            id={`cortex-how-connect-node-${i}`}
            cx={node.x}
            cy={node.y}
            r={7}
            fill="#FFFFFF"
            stroke="#111111"
            strokeWidth={1.2}
            animate={settled && animate ? { scale: [1, 1.18, 1] } : { scale: 1 }}
            transition={{ duration: 0.9, delay: i * 0.08 }}
            style={{ transformBox: "fill-box", transformOrigin: "center" }}
          />
        ))}
      </svg>
    </div>
  );
}

const REASON_PAIRS = [
  {
    question: "Who are our most calibrated interviewers?",
    answer: "Sarah and Dev — 92% alignment with final outcomes.",
    evidence: "Based on 47 interviews this quarter",
  },
  {
    question: "Why did we pass on similar candidates before?",
    answer: "3 of 4 lacked depth in distributed systems.",
    evidence: "Linked to 4 onsite transcripts",
  },
  {
    question: "What predicts success in this role?",
    answer: "Strong trade-off reasoning in systems design rounds.",
    evidence: "Pattern across 12 successful hires",
  },
];

function ReasonVisual({ animate }: { animate: boolean }) {
  const [pairIndex, setPairIndex] = useState(0);
  const [phase, setPhase] = useState(2); // 0 = question, 1 = thinking, 2 = answer

  useEffect(() => {
    if (!animate) return;
    const timings = [900, 1100, 3200];
    const timer = setTimeout(() => {
      if (phase < 2) {
        setPhase(phase + 1);
      } else {
        setPhase(0);
        setPairIndex((i) => (i + 1) % REASON_PAIRS.length);
      }
    }, timings[phase]);
    return () => clearTimeout(timer);
  }, [animate, phase, pairIndex]);

  const pair = REASON_PAIRS[pairIndex];

  return (
    <div id="cortex-how-reason-visual" className="h-full flex flex-col justify-center gap-2 px-4">
      <motion.div
        key={`q-${pairIndex}`}
        id={`cortex-how-reason-question-${pairIndex}`}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="self-end max-w-[85%] bg-[#111111] text-white text-[11px] leading-snug px-3 py-2 rounded-2xl rounded-br-md"
      >
        {pair.question}
      </motion.div>
      <div className="self-start max-w-[90%] min-h-[58px]">
        <AnimatePresence mode="wait">
          {phase === 1 && (
            <motion.div
              key="thinking"
              id="cortex-how-reason-thinking"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex items-center gap-1.5 bg-white border border-[var(--lp-border)] rounded-2xl rounded-bl-md px-3 py-2.5 w-fit"
            >
              {[0, 1, 2].map((d) => (
                <motion.span
                  key={d}
                  className="w-1.5 h-1.5 rounded-full bg-[#737373]"
                  animate={{ opacity: [0.3, 1, 0.3] }}
                  transition={{ duration: 1, repeat: Infinity, delay: d * 0.2 }}
                />
              ))}
            </motion.div>
          )}
          {phase === 2 && (
            <motion.div
              key={`a-${pairIndex}`}
              id={`cortex-how-reason-answer-${pairIndex}`}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="bg-white border border-[var(--lp-border)] rounded-2xl rounded-bl-md px-3 py-2"
            >
              <p className="text-[11px] text-[#111111] leading-snug">{pair.answer}</p>
              <p className="flex items-center gap-1 text-[10px] text-[#737373] mt-1">
                <Search className="w-2.5 h-2.5" />
                {pair.evidence}
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

const STEPS = [
  {
    id: "capture",
    number: "01",
    title: "Capture everything",
    description:
      "Every intake call, interview, scorecard, and decision streams into Cortex as it happens — nothing to file, nothing to remember.",
    Visual: CaptureVisual,
  },
  {
    id: "connect",
    number: "02",
    title: "Connect the dots",
    description:
      "Entities are resolved and linked — this candidate, that round, those skills. Signal compounds instead of scattering across tools.",
    Visual: ConnectVisual,
  },
  {
    id: "reason",
    number: "03",
    title: "Reason with receipts",
    description:
      "Leaders and AI agents query the graph in plain English and get answers backed by evidence — not vibes.",
    Visual: ReasonVisual,
  },
];

const containerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.12 } },
};

const cardVariants = {
  hidden: { opacity: 0, y: 24 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

function CortexHowItWorks() {
  const prefersReducedMotion = useReducedMotion();
  const animate = !prefersReducedMotion;

  return (
    <section id="cortex-how-section" className="py-20 md:py-28 bg-[var(--lp-surface)]/60">
      <div id="cortex-how-inner" className="max-w-[1100px] mx-auto px-6">
        <p
          id="cortex-how-eyebrow"
          className="font-mono-label text-xs tracking-[0.2em] uppercase text-[var(--lp-text-muted)] text-center mb-4"
        >
          How it works
        </p>
        <h2
          id="cortex-how-title"
          className="font-display text-4xl md:text-5xl font-light text-[var(--lp-text-primary)] text-center mb-5"
        >
          Signal in. Intelligence out.
        </h2>
        <p
          id="cortex-how-subtitle"
          className="text-base md:text-lg text-[var(--lp-text-secondary)] text-center max-w-2xl mx-auto mb-14"
        >
          No new workflows. Cortex listens to the hiring work you already do and turns it into a
          brain your whole org can query.
        </p>

        <motion.div
          id="cortex-how-cards"
          className="grid grid-cols-1 md:grid-cols-3 gap-5"
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-80px" }}
        >
          {STEPS.map((step) => (
            <motion.div
              key={step.id}
              id={`cortex-how-card-${step.id}`}
              variants={cardVariants}
              className="bg-[var(--lp-bg)] border border-[var(--lp-border)] rounded-xl p-6 flex flex-col hover:-translate-y-1 transition-transform duration-200"
            >
              <div id={`cortex-how-card-visual-${step.id}`} className="h-44 rounded-lg bg-[var(--lp-surface)] border border-[var(--lp-border)] overflow-hidden mb-5">
                <step.Visual animate={animate} />
              </div>
              <p
                id={`cortex-how-card-number-${step.id}`}
                className="font-mono-label text-[10px] tracking-[0.25em] text-[var(--lp-text-faint)] mb-2"
              >
                {step.number}
              </p>
              <h3
                id={`cortex-how-card-title-${step.id}`}
                className="font-display text-xl font-medium text-[var(--lp-text-primary)] mb-2"
              >
                {step.title}
              </h3>
              <p
                id={`cortex-how-card-desc-${step.id}`}
                className="text-sm text-[var(--lp-text-secondary)] leading-relaxed"
              >
                {step.description}
              </p>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}

export { CortexHowItWorks };
