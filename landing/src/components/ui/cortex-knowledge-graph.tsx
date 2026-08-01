"use client";

import { useState } from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import {
  Briefcase,
  User,
  Mic,
  FileText,
  ClipboardCheck,
  Users,
  Sparkles,
  CheckCircle2,
  BrainCircuit,
  type LucideIcon,
} from "lucide-react";

const CENTER = 280;

interface GraphNode {
  id: string;
  label: string;
  icon: LucideIcon;
  x: number;
  y: number;
  bend: number;
  caption: { title: string; body: string };
}

const CORE_CAPTION = {
  title: "The Cortex core",
  body: "Every signal lands in one living graph — scoped to your org, growing sharper with every interview you run.",
};

const NODES: GraphNode[] = [
  {
    id: "requisition",
    label: "Requisitions",
    icon: Briefcase,
    x: 280,
    y: 78,
    bend: 26,
    caption: {
      title: "Requisitions",
      body: "Every role’s bar, must-haves, and intent — captured from intake conversations, not guessed at later.",
    },
  },
  {
    id: "candidate",
    label: "Candidates",
    icon: User,
    x: 428,
    y: 136,
    bend: -22,
    caption: {
      title: "Candidates",
      body: "A candidate’s full journey resolved to one identity — every round, every piece of evidence, every outcome.",
    },
  },
  {
    id: "interview",
    label: "Interviews",
    icon: Mic,
    x: 482,
    y: 286,
    bend: 24,
    caption: {
      title: "Interviews",
      body: "Every conversation becomes structured signal — not a memory that fades by Friday’s debrief.",
    },
  },
  {
    id: "feedback",
    label: "Feedback",
    icon: ClipboardCheck,
    x: 424,
    y: 428,
    bend: -24,
    caption: {
      title: "Feedback",
      body: "Structured scorecards linked to the exact moments in the interview that earned them.",
    },
  },
  {
    id: "decision",
    label: "Decisions",
    icon: CheckCircle2,
    x: 280,
    y: 484,
    bend: 24,
    caption: {
      title: "Decisions",
      body: "Hires and passes tied back to the evidence that drove them — and to what happened next.",
    },
  },
  {
    id: "interviewer",
    label: "Interviewers",
    icon: Users,
    x: 134,
    y: 426,
    bend: -26,
    caption: {
      title: "Interviewers",
      body: "Who rates how. Consistency, calibration, and drift — visible per interviewer, over time.",
    },
  },
  {
    id: "transcript",
    label: "Transcripts",
    icon: FileText,
    x: 80,
    y: 284,
    bend: 22,
    caption: {
      title: "Transcripts",
      body: "Word-for-word evidence behind every score. Receipts, available on demand.",
    },
  },
  {
    id: "skill",
    label: "Skills",
    icon: Sparkles,
    x: 136,
    y: 138,
    bend: -24,
    caption: {
      title: "Skills",
      body: "Competencies connected across roles, so “strong in systems design” means one thing everywhere.",
    },
  },
];

// Faint entity-to-entity links that show the graph is a web, not a hub-and-spoke.
const CROSS_LINKS: Array<[string, string]> = [
  ["candidate", "interview"],
  ["interview", "transcript"],
  ["interview", "feedback"],
  ["feedback", "decision"],
  ["interviewer", "feedback"],
  ["requisition", "skill"],
];

function edgePath(node: GraphNode): string {
  const mx = (node.x + CENTER) / 2;
  const my = (node.y + CENTER) / 2;
  const dx = CENTER - node.x;
  const dy = CENTER - node.y;
  const len = Math.hypot(dx, dy) || 1;
  const px = (-dy / len) * node.bend;
  const py = (dx / len) * node.bend;
  return `M ${node.x} ${node.y} Q ${mx + px} ${my + py} ${CENTER} ${CENTER}`;
}

const nodeById = (id: string) => NODES.find((n) => n.id === id) as GraphNode;

function CortexKnowledgeGraph() {
  const [activeId, setActiveId] = useState<string | null>(null);
  const prefersReducedMotion = useReducedMotion();

  const activeCaption = activeId ? nodeById(activeId).caption : CORE_CAPTION;
  const ActiveIcon = activeId ? nodeById(activeId).icon : BrainCircuit;

  return (
    <section id="cortex-graph-section" className="py-20 md:py-28 bg-[var(--lp-bg)]">
      <div id="cortex-graph-inner" className="max-w-[1100px] mx-auto px-6">
        <div
          id="cortex-graph-layout"
          className="grid grid-cols-1 lg:grid-cols-[5fr_6fr] gap-10 lg:gap-16 items-center"
        >
          {/* Copy + caption panel */}
          <motion.div
            id="cortex-graph-copy"
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-100px" }}
            transition={{ duration: 0.6 }}
          >
            <p
              id="cortex-graph-eyebrow"
              className="font-mono-label text-xs tracking-[0.2em] uppercase text-[var(--lp-text-muted)] mb-4"
            >
              What is Cortex
            </p>
            <h2
              id="cortex-graph-title"
              className="font-display text-4xl md:text-5xl font-light text-[var(--lp-text-primary)] mb-5 leading-[1.12]"
            >
              One graph.
              <br />
              Every hiring signal.
            </h2>
            <p
              id="cortex-graph-description"
              className="text-base md:text-lg text-[var(--lp-text-secondary)] leading-relaxed mb-8 max-w-xl"
            >
              Cortex is a living knowledge graph of your hiring. Every requisition, interview,
              scorecard, and decision flows in, gets connected, and becomes something your whole
              team can reason over — in plain English.
            </p>

            {/* Caption panel — swaps as you explore the graph */}
            <div
              id="cortex-graph-caption-panel"
              className="bg-[var(--lp-surface)] border border-[var(--lp-border)] rounded-xl p-5 min-h-[124px]"
            >
              <AnimatePresence mode="wait">
                <motion.div
                  key={activeCaption.title}
                  id="cortex-graph-caption-content"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.22 }}
                >
                  <div id="cortex-graph-caption-head" className="flex items-center gap-2.5 mb-2">
                    <span
                      id="cortex-graph-caption-icon"
                      className="w-7 h-7 rounded-full bg-[#111111] text-white flex items-center justify-center"
                    >
                      <ActiveIcon className="w-3.5 h-3.5" />
                    </span>
                    <h3
                      id="cortex-graph-caption-title"
                      className="text-sm font-semibold text-[var(--lp-text-primary)]"
                    >
                      {activeCaption.title}
                    </h3>
                  </div>
                  <p
                    id="cortex-graph-caption-body"
                    className="text-sm text-[var(--lp-text-secondary)] leading-relaxed"
                  >
                    {activeCaption.body}
                  </p>
                </motion.div>
              </AnimatePresence>
            </div>
            <p
              id="cortex-graph-hint"
              className="font-mono-label text-[10px] tracking-[0.2em] uppercase text-[var(--lp-text-faint)] mt-3"
            >
              Hover a node to see what it carries
            </p>
          </motion.div>

          {/* The graph */}
          <motion.div
            id="cortex-graph-canvas-wrap"
            className="relative w-full max-w-[560px] mx-auto"
            initial={{ opacity: 0, scale: 0.96 }}
            whileInView={{ opacity: 1, scale: 1 }}
            viewport={{ once: true, margin: "-100px" }}
            transition={{ duration: 0.7 }}
          >
            <svg
              id="cortex-graph-svg"
              viewBox="0 0 560 560"
              className="w-full h-auto select-none"
              role="img"
              aria-label="Cortex knowledge graph connecting requisitions, candidates, interviews, transcripts, feedback, interviewers, skills, and decisions"
            >
              {/* Cross links (entity to entity) */}
              {CROSS_LINKS.map(([a, b]) => {
                const na = nodeById(a);
                const nb = nodeById(b);
                const dim =
                  activeId !== null && activeId !== a && activeId !== b;
                return (
                  <line
                    key={`${a}-${b}`}
                    id={`cortex-graph-crosslink-${a}-${b}`}
                    x1={na.x}
                    y1={na.y}
                    x2={nb.x}
                    y2={nb.y}
                    stroke={!dim && activeId !== null ? "#9A958E" : "#E5E3DF"}
                    strokeWidth={1}
                    strokeDasharray="3 5"
                    opacity={dim ? 0.35 : 0.8}
                    className="transition-all duration-300"
                  />
                );
              })}

              {/* Spokes to the core + traveling pulses */}
              {NODES.map((node, i) => {
                const path = edgePath(node);
                const isActive = activeId === node.id;
                const isDimmed = activeId !== null && !isActive;
                return (
                  <g key={node.id} id={`cortex-graph-edge-group-${node.id}`}>
                    <path
                      id={`cortex-graph-edge-${node.id}`}
                      d={path}
                      fill="none"
                      stroke={isActive ? "#111111" : "#D8D5D0"}
                      strokeWidth={isActive ? 1.8 : 1.2}
                      opacity={isDimmed ? 0.3 : 1}
                      className="transition-all duration-300"
                    />
                    {!prefersReducedMotion && (
                      <circle
                        id={`cortex-graph-pulse-${node.id}`}
                        r={2.5}
                        fill="#111111"
                        opacity={isDimmed ? 0.15 : 0.6}
                        className="transition-opacity duration-300"
                      >
                        <animateMotion
                          dur={`${3.4 + i * 0.35}s`}
                          begin={`${i * 0.5}s`}
                          repeatCount="indefinite"
                          path={path}
                        />
                      </circle>
                    )}
                  </g>
                );
              })}

              {/* Core */}
              <g id="cortex-graph-core">
                <circle
                  id="cortex-graph-core-halo"
                  cx={CENTER}
                  cy={CENTER}
                  r={84}
                  fill="none"
                  stroke="#E5E3DF"
                  strokeWidth={1}
                />
                {!prefersReducedMotion ? (
                  <motion.circle
                    id="cortex-graph-core-ring"
                    cx={CENTER}
                    cy={CENTER}
                    r={70}
                    fill="none"
                    stroke="#B7B2AB"
                    strokeWidth={1}
                    strokeDasharray="4 9"
                    style={{ transformBox: "fill-box", transformOrigin: "center" }}
                    animate={{ rotate: 360 }}
                    transition={{ duration: 60, repeat: Infinity, ease: "linear" }}
                  />
                ) : (
                  <circle
                    id="cortex-graph-core-ring"
                    cx={CENTER}
                    cy={CENTER}
                    r={70}
                    fill="none"
                    stroke="#B7B2AB"
                    strokeWidth={1}
                    strokeDasharray="4 9"
                  />
                )}
                <circle
                  id="cortex-graph-core-disc"
                  cx={CENTER}
                  cy={CENTER}
                  r={56}
                  fill="#111111"
                />
                <g id="cortex-graph-core-icon" transform={`translate(${CENTER - 11}, ${CENTER - 22})`}>
                  <BrainCircuit size={22} color="#FFFFFF" strokeWidth={1.6} />
                </g>
                <text
                  id="cortex-graph-core-label"
                  x={CENTER}
                  y={CENTER + 18}
                  textAnchor="middle"
                  fill="#FFFFFF"
                  fontSize={15}
                  className="font-display"
                >
                  Cortex
                </text>
              </g>

              {/* Entity nodes */}
              {NODES.map((node, i) => {
                const Icon = node.icon;
                const isActive = activeId === node.id;
                const isDimmed = activeId !== null && !isActive;
                const labelBelow = node.y >= CENTER;
                return (
                  <motion.g
                    key={node.id}
                    id={`cortex-graph-node-${node.id}`}
                    role="button"
                    tabIndex={0}
                    aria-label={`${node.label}: ${node.caption.body}`}
                    className="cursor-pointer focus:outline-none"
                    style={{ transformBox: "fill-box", transformOrigin: "center" }}
                    animate={
                      prefersReducedMotion
                        ? undefined
                        : { y: [0, -4, 0] }
                    }
                    transition={
                      prefersReducedMotion
                        ? undefined
                        : { duration: 4 + i * 0.35, repeat: Infinity, ease: "easeInOut" }
                    }
                    whileHover={{ scale: 1.07 }}
                    onMouseEnter={() => setActiveId(node.id)}
                    onMouseLeave={() => setActiveId(null)}
                    onFocus={() => setActiveId(node.id)}
                    onBlur={() => setActiveId(null)}
                    onClick={() => setActiveId(isActive ? null : node.id)}
                  >
                    <circle
                      id={`cortex-graph-node-circle-${node.id}`}
                      cx={node.x}
                      cy={node.y}
                      r={26}
                      fill="#FFFFFF"
                      stroke={isActive ? "#111111" : "#E5E3DF"}
                      strokeWidth={isActive ? 1.6 : 1}
                      opacity={isDimmed ? 0.55 : 1}
                      className="transition-all duration-300"
                    />
                    <g
                      id={`cortex-graph-node-icon-${node.id}`}
                      transform={`translate(${node.x - 9}, ${node.y - 9})`}
                      opacity={isDimmed ? 0.45 : 1}
                      className="transition-opacity duration-300"
                    >
                      <Icon
                        size={18}
                        color={isActive ? "#111111" : "#555555"}
                        strokeWidth={1.8}
                      />
                    </g>
                    <text
                      id={`cortex-graph-node-label-${node.id}`}
                      x={node.x}
                      y={labelBelow ? node.y + 44 : node.y - 36}
                      textAnchor="middle"
                      fontSize={11.5}
                      fill={isActive ? "#111111" : "#737373"}
                      fontWeight={isActive ? 600 : 400}
                      opacity={isDimmed ? 0.5 : 1}
                      className="transition-all duration-300"
                    >
                      {node.label}
                    </text>
                  </motion.g>
                );
              })}
            </svg>
          </motion.div>
        </div>
      </div>
    </section>
  );
}

export { CortexKnowledgeGraph };
