"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { DitheredOrb } from "@/components/ui/dithered-orb";
import { FeedbackScorecard } from "@/components/feedback/FeedbackScorecard";
import type { RatingValue, QuestionData } from "@/components/feedback/FeedbackScorecard";
import {
  FileText,
  ClipboardCheck,
  Bot,
  PenLine,
  FileCheck,
  Check,
  CheckCircle,
  ClipboardList,
  Loader2,
} from "lucide-react";

type DemoStep = "round-intake" | "interview-plan" | "live-interview" | "ai-feedback" | "hiring-packet";
type LiveInterviewSubState = "interview" | "candidate-left" | "activating" | "collecting" | "leaving";

interface DemoRound {
  id: string;
  name: string;
  roundType: "interview" | "assessment";
  duration: string;
  questions: QuestionData[];
  targetRating: RatingValue;
  targetSummary: string;
  targetQuestionSummaries: Record<string, string>;
}

const STEP_META = [
  { id: "round-intake" as DemoStep, label: "Voice Intake with OpenRecruiting", icon: FileText, description: "Have a voice conversation with OpenRecruiting to define your role, tech stack, and hiring bar — the AI builds a tailored interview plan.", blurb: "Tell OpenRecruiting about the role, get a plan" },
  { id: "interview-plan" as DemoStep, label: "Custom Scorecards Created", icon: ClipboardCheck, description: "OpenRecruiting generates structured scorecards for every round — calibrated to your role requirements and evaluation criteria.", blurb: "Scorecards built for every round" },
  { id: "live-interview" as DemoStep, label: "OpenRecruiting Collects Feedback Over Voice", icon: Bot, description: "The bot is already in the call. The moment the candidate drops, it turns to the panel and collects structured feedback over voice — while the interview is still fresh.", blurb: "Voice-driven feedback from the panel" },
  { id: "ai-feedback" as DemoStep, label: "Auto-Fill Feedback", icon: PenLine, description: "Spoken answers become a filled scorecard, each rating tied to what was actually said — no forms, no chasing.", blurb: "Feedback filled automatically" },
  { id: "hiring-packet" as DemoStep, label: "Evidence-Based Packet Created", icon: FileCheck, description: "Ratings, summaries and transcript-level evidence across every round — ready for the debrief, and queryable in Cortex afterwards.", blurb: "Full packet with evidence, ready to review" },
];

const INTAKE_TRANSCRIPT = [
  { speaker: "ai", text: "Hi! I\u2019m OpenRecruiting. Let\u2019s set up your interview process. What role are you hiring for?" },
  { speaker: "user", text: "We need a Senior Backend Engineer for our platform team." },
  { speaker: "ai", text: "Got it. What\u2019s the tech stack for this role?" },
  { speaker: "user", text: "Java 17, Spring Boot, PostgreSQL, Redis, Kafka on AWS." },
  { speaker: "ai", text: "What should they accomplish in their first 90 days?" },
  { speaker: "user", text: "Redesign our payment pipeline to cut latency by 50%." },
  { speaker: "ai", text: "Perfect. I\u2019ll generate an interview plan with 4 rounds tailored to this role." },
];

const FEEDBACK_TRANSCRIPT = [
  { speaker: "ai", text: "Thanks Sarah. I\u2019ve captured the full interview. How would you rate John\u2019s problem-solving approach?" },
  { speaker: "interviewer", text: "Strong. He broke down the payment pipeline problem methodically and caught edge cases I didn\u2019t even prompt." },
  { speaker: "ai", text: "What about his handling of concurrent transactions?" },
  { speaker: "interviewer", text: "Impressive \u2014 the optimistic locking with event sourcing approach showed real production experience." },
  { speaker: "ai", text: "Any concerns or areas for improvement?" },
  { speaker: "interviewer", text: "He could be more concise in explanations, but technically very strong. I\u2019d say Strong Yes." },
];

const DEMO_ROUNDS: DemoRound[] = [
  {
    id: "ps", name: "Problem Solving", roundType: "interview", duration: "45 mins",
    questions: [
      { question_number: 1, question_text: "Problem decomposition ability", description: "Can the candidate break down complex problems into smaller, manageable parts?" },
      { question_number: 2, question_text: "Code quality and readability", description: "Does the candidate write clean, well-structured code?" },
      { question_number: 3, question_text: "Edge case handling", description: "Does the candidate proactively identify and handle edge cases?" },
    ],
    targetRating: "strong_yes",
    targetSummary: "Excellent problem-solving skills. Broke down the payment pipeline challenge methodically, identified edge cases around concurrent transactions unprompted.",
    targetQuestionSummaries: { "1": "Decomposed the payment processing problem into clear modules.", "2": "Clean code with meaningful variable names.", "3": "Caught race conditions in concurrent payment processing." },
  },
  {
    id: "mc", name: "Machine Coding", roundType: "assessment", duration: "60 mins",
    questions: [
      { question_number: 1, question_text: "Object-oriented design", description: "Does the candidate apply solid OOP principles?" },
      { question_number: 2, question_text: "Code extensibility", description: "Is the code designed for future changes and extensions?" },
      { question_number: 3, question_text: "Working demo quality", description: "Does the implementation work end-to-end with proper error handling?" },
    ],
    targetRating: "yes",
    targetSummary: "Strong implementation skills. Built a working payment gateway simulator with clean separation of concerns.",
    targetQuestionSummaries: { "1": "Good use of interfaces and abstract classes.", "2": "Strategy pattern for payment providers.", "3": "Demo worked end-to-end." },
  },
  {
    id: "sd", name: "Systems Design", roundType: "interview", duration: "45 mins",
    questions: [
      { question_number: 1, question_text: "Requirements clarification", description: "Does the candidate ask the right questions before designing?" },
      { question_number: 2, question_text: "Trade-off analysis", description: "Can the candidate articulate trade-offs between different approaches?" },
      { question_number: 3, question_text: "Scalability considerations", description: "Does the design account for growth and scale?" },
    ],
    targetRating: "strong_yes",
    targetSummary: "Outstanding systems thinking. Designed a payment processing system handling 10K TPS with clear trade-off analysis.",
    targetQuestionSummaries: { "1": "Asked about TPS, consistency, currencies.", "2": "Articulated trade-offs between sync vs async.", "3": "Designed with horizontal scaling in mind." },
  },
  {
    id: "bh", name: "Behavioural", roundType: "interview", duration: "30 mins",
    questions: [
      { question_number: 1, question_text: "Leadership examples", description: "Can the candidate demonstrate leadership in past roles?" },
      { question_number: 2, question_text: "Conflict resolution", description: "How does the candidate handle disagreements?" },
      { question_number: 3, question_text: "Communication clarity", description: "Can the candidate explain complex topics clearly?" },
    ],
    targetRating: "yes",
    targetSummary: "Good leadership signals. Led a team of 4 through a critical migration. Communicates clearly.",
    targetQuestionSummaries: { "1": "Led migration of monolith to microservices.", "2": "Data-driven resolution of disagreements.", "3": "Explains technical concepts well." },
  },
];

const TIMINGS = { TRANSCRIPT_DELAY: 900, ROUND_APPEAR_DELAY: 500, ROUND_CONFIG_DELAY: 700, STEP_PAUSE: 600 };

const ratingLabel = (r: RatingValue) => {
  const map: Record<RatingValue, string> = { strong_yes: "Strong Yes", yes: "Yes", maybe: "Maybe", no: "No", strong_no: "Strong No" };
  return map[r];
};

const ratingColor = (r: RatingValue) => {
  if (r === "strong_yes" || r === "yes") return "bg-emerald-50 text-emerald-700";
  if (r === "maybe") return "bg-amber-50 text-amber-700";
  return "bg-red-50 text-red-700";
};

function FromPlanToDecision() {
  const [activeStep, setActiveStep] = useState<DemoStep>("round-intake");
  const [isAutoPlaying, setIsAutoPlaying] = useState(true);

  // Intake state
  const [visibleMessages, setVisibleMessages] = useState(0);
  const [orbState, setOrbState] = useState<"idle" | "listening" | "processing">("idle");
  const [fakeAudioLevel, setFakeAudioLevel] = useState(0);

  // Interview plan state
  const [visibleRoundsCount, setVisibleRoundsCount] = useState(0);
  const [selectedRoundIndex, setSelectedRoundIndex] = useState(0);
  const [configuredRoundIndex, setConfiguredRoundIndex] = useState(-1);

  // Live interview state
  const [liveSubState, setLiveSubState] = useState<LiveInterviewSubState>("interview");
  const [feedbackMsgCount, setFeedbackMsgCount] = useState(0);

  // AI Feedback state
  const [feedbackPhase, setFeedbackPhase] = useState(0); // 0=nothing, 1=rating, 2=summary, 3=q1, 4=q2, 5=done

  // Hiring packet state
  const [visiblePacketRounds, setVisiblePacketRounds] = useState(0);
  const [showPacketCta, setShowPacketCta] = useState(false);
  const [visibleEvidence, setVisibleEvidence] = useState<Record<number, number>>({}); // roundIndex -> visible evidence count

  const transcriptRef = useRef<HTMLDivElement>(null);
  const interviewTranscriptRef = useRef<HTMLDivElement>(null);

  const resetAllState = useCallback(() => {
    setVisibleMessages(0);
    setOrbState("idle");
    setFakeAudioLevel(0);
    setVisibleRoundsCount(0);
    setSelectedRoundIndex(0);
    setConfiguredRoundIndex(-1);
    setLiveSubState("interview");
    setFeedbackMsgCount(0);
    setFeedbackPhase(0);
    setVisiblePacketRounds(0);
    setShowPacketCta(false);
    setVisibleEvidence({});
  }, []);

  const goToStep = useCallback((step: DemoStep) => {
    resetAllState();
    setActiveStep(step);
    setIsAutoPlaying(false);
  }, [resetAllState]);

  const advanceToStep = useCallback((step: DemoStep) => {
    resetAllState();
    setActiveStep(step);
  }, [resetAllState]);

  // Fake audio level for orb
  useEffect(() => {
    if (orbState !== "listening") return;
    const interval = setInterval(() => setFakeAudioLevel(0.3 + Math.random() * 0.6), 100);
    return () => clearInterval(interval);
  }, [orbState]);

  // === Intake Call ===
  useEffect(() => {
    if (activeStep !== "round-intake") return;
    if (visibleMessages < INTAKE_TRANSCRIPT.length) {
      const msg = INTAKE_TRANSCRIPT[visibleMessages];
      setOrbState(msg.speaker === "user" ? "listening" : "processing");
      const timer = setTimeout(() => {
        setVisibleMessages(prev => prev + 1);
        if (transcriptRef.current) transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
      }, TIMINGS.TRANSCRIPT_DELAY);
      return () => clearTimeout(timer);
    } else {
      setOrbState("processing");
      const timer = setTimeout(() => {
        setOrbState("idle");
        if (isAutoPlaying) advanceToStep("interview-plan");
      }, TIMINGS.STEP_PAUSE);
      return () => clearTimeout(timer);
    }
  }, [activeStep, visibleMessages, isAutoPlaying, advanceToStep]);

  // === Interview Plan ===
  useEffect(() => {
    if (activeStep !== "interview-plan") return;
    if (visibleRoundsCount < DEMO_ROUNDS.length) {
      const timer = setTimeout(() => setVisibleRoundsCount(prev => prev + 1), TIMINGS.ROUND_APPEAR_DELAY);
      return () => clearTimeout(timer);
    } else if (configuredRoundIndex < DEMO_ROUNDS.length - 1) {
      const timer = setTimeout(() => {
        const next = configuredRoundIndex + 1;
        setConfiguredRoundIndex(next);
        setSelectedRoundIndex(next);
      }, TIMINGS.ROUND_CONFIG_DELAY);
      return () => clearTimeout(timer);
    } else {
      const timer = setTimeout(() => {
        if (isAutoPlaying) advanceToStep("live-interview");
      }, TIMINGS.STEP_PAUSE);
      return () => clearTimeout(timer);
    }
  }, [activeStep, visibleRoundsCount, configuredRoundIndex, isAutoPlaying, advanceToStep]);

  // === Live Interview init ===
  useEffect(() => {
    if (activeStep !== "live-interview") return;
    setLiveSubState("interview");
    setFeedbackMsgCount(0);
    setOrbState("idle");
  }, [activeStep]);

  // === Live Interview sub-states ===
  useEffect(() => {
    if (activeStep !== "live-interview") return;
    let timer: ReturnType<typeof setTimeout>;
    if (liveSubState === "interview") timer = setTimeout(() => setLiveSubState("candidate-left"), 2400);
    else if (liveSubState === "candidate-left") timer = setTimeout(() => setLiveSubState("activating"), 1600);
    else if (liveSubState === "activating") timer = setTimeout(() => { setLiveSubState("collecting"); setOrbState("listening"); }, 2000);
    return () => clearTimeout(timer);
  }, [activeStep, liveSubState]);

  // === Live Interview feedback messages ===
  useEffect(() => {
    if (activeStep !== "live-interview" || liveSubState !== "collecting") return;
    if (feedbackMsgCount < FEEDBACK_TRANSCRIPT.length) {
      const timer = setTimeout(() => {
        setFeedbackMsgCount(prev => prev + 1);
        if (interviewTranscriptRef.current) interviewTranscriptRef.current.scrollTop = interviewTranscriptRef.current.scrollHeight;
      }, 2000);
      return () => clearTimeout(timer);
    } else {
      setLiveSubState("leaving");
      setOrbState("processing");
    }
  }, [activeStep, liveSubState, feedbackMsgCount]);

  // === Live Interview leaving ===
  useEffect(() => {
    if (activeStep !== "live-interview" || liveSubState !== "leaving") return;
    const timer = setTimeout(() => { if (isAutoPlaying) advanceToStep("ai-feedback"); }, 2000);
    return () => clearTimeout(timer);
  }, [activeStep, liveSubState, isAutoPlaying, advanceToStep]);

  // === AI Feedback animated fill-in ===
  useEffect(() => {
    if (activeStep !== "ai-feedback") return;
    if (feedbackPhase < 5) {
      const timer = setTimeout(() => setFeedbackPhase(prev => prev + 1), feedbackPhase === 0 ? 400 : 800);
      return () => clearTimeout(timer);
    } else {
      const timer = setTimeout(() => { if (isAutoPlaying) advanceToStep("hiring-packet"); }, 1500);
      return () => clearTimeout(timer);
    }
  }, [activeStep, feedbackPhase, isAutoPlaying, advanceToStep]);

  // === Hiring Packet ===
  useEffect(() => {
    if (activeStep !== "hiring-packet") return;
    setVisiblePacketRounds(0);
    setShowPacketCta(false);
    setVisibleEvidence({});
    const timers: ReturnType<typeof setTimeout>[] = [];
    const roundDelay = 600;
    const evidenceDelay = 350;
    DEMO_ROUNDS.forEach((round, index) => {
      const roundTime = (index + 1) * roundDelay;
      timers.push(setTimeout(() => setVisiblePacketRounds(index + 1), roundTime));
      // Show evidence items for each round after it appears
      const evidenceCount = Object.keys(round.targetQuestionSummaries).length;
      for (let e = 0; e < evidenceCount; e++) {
        timers.push(setTimeout(() => {
          setVisibleEvidence(prev => ({ ...prev, [index]: (prev[index] || 0) + 1 }));
        }, roundTime + (e + 1) * evidenceDelay));
      }
    });
    const totalEvidenceTime = DEMO_ROUNDS.length * roundDelay + Object.keys(DEMO_ROUNDS[DEMO_ROUNDS.length - 1].targetQuestionSummaries).length * evidenceDelay;
    timers.push(setTimeout(() => setShowPacketCta(true), totalEvidenceTime + 600));
    timers.push(setTimeout(() => {
      if (isAutoPlaying) {
        resetAllState();
        setActiveStep("round-intake");
      }
    }, totalEvidenceTime + 3500));
    return () => timers.forEach(clearTimeout);
  }, [activeStep, isAutoPlaying, resetAllState]);

  const activeStepIndex = STEP_META.findIndex(s => s.id === activeStep);

  // ─── Render Functions ───

  const renderIntake = () => (
    <motion.div key="intake" initial={{ opacity: 0, x: 30 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -30 }} className="flex flex-col gap-4 h-full">
      <div className="bg-[#F2F0ED] rounded-2xl border border-[#E5E3DF] p-4 md:p-6">
        <div className="grid grid-cols-2 gap-4 md:gap-6">
          <div className="flex flex-col items-center gap-2">
            <div className="w-[100px] h-[100px] md:w-[130px] md:h-[130px]">
              <DitheredOrb state={orbState} audioLevel={fakeAudioLevel} />
            </div>
            <p className="text-xs md:text-sm font-semibold text-[#111111]">OpenRecruiting</p>
          </div>
          <div className="flex flex-col items-center gap-2 justify-center">
            <div className="w-[70px] h-[70px] md:w-[90px] md:h-[90px] rounded-full bg-[#E5E3DF] flex items-center justify-center">
              <span className="text-xl md:text-2xl font-bold text-[#555555]">You</span>
            </div>
            <p className="text-xs md:text-sm font-semibold text-[#111111]">Recruiter</p>
          </div>
        </div>
      </div>
      <div ref={transcriptRef} className="flex-1 max-h-[200px] overflow-y-auto space-y-2.5 pr-2">
        {INTAKE_TRANSCRIPT.slice(0, visibleMessages).map((msg, i) => (
          <motion.div key={i} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className={`flex ${msg.speaker === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[80%] px-3 py-2 rounded-2xl text-sm ${msg.speaker === "user" ? "bg-[#111111] text-white rounded-br-md" : "bg-[#F2F0ED] text-[#111111] border border-[#E5E3DF] rounded-bl-md"}`}>
              {msg.text}
            </div>
          </motion.div>
        ))}
      </div>
    </motion.div>
  );

  const renderPlan = () => (
    <motion.div key="plan" initial={{ opacity: 0, x: 30 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -30 }} className="flex flex-col gap-4 h-full overflow-y-auto">
      <div className="space-y-3">
        {DEMO_ROUNDS.slice(0, visibleRoundsCount).map((round, index) => (
          <motion.div key={round.id} initial={{ opacity: 0, x: -15 }} animate={{ opacity: 1, x: 0 }}
            className={`flex items-center gap-3 p-3 rounded-xl border transition-all cursor-pointer ${index === selectedRoundIndex ? "bg-white border-[#111111]/20 shadow-sm" : "bg-[#F2F0ED] border-[#E5E3DF]"}`}
            onClick={() => setSelectedRoundIndex(index)}
          >
            <div className={`w-6 h-6 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${index <= configuredRoundIndex ? "border-green-500 bg-green-500" : index === selectedRoundIndex ? "border-[#111111]" : "border-[#E5E3DF]"}`}>
              {index <= configuredRoundIndex && <Check className="w-3 h-3 text-white" />}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-[#111111]">{round.name}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded ${round.roundType === "assessment" ? "bg-amber-100 text-amber-700" : "bg-blue-100 text-blue-700"}`}>
                  {round.roundType === "assessment" ? "Assessment" : "Interview"}
                </span>
              </div>
              <span className="text-xs text-[#888888]">{round.duration}</span>
            </div>
          </motion.div>
        ))}
      </div>
      {configuredRoundIndex >= 0 && (
        <div className="bg-white rounded-xl border border-[#E5E3DF] p-4 mt-2">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-bold text-[#111111]">Configuring: {DEMO_ROUNDS[Math.min(configuredRoundIndex, DEMO_ROUNDS.length - 1)].name}</h3>
            <span className="px-2 py-0.5 text-xs border border-orange-400 text-orange-600 rounded bg-orange-50">
              {DEMO_ROUNDS[Math.min(configuredRoundIndex, DEMO_ROUNDS.length - 1)].duration}
            </span>
          </div>
          <div className="space-y-2">
            {DEMO_ROUNDS[Math.min(configuredRoundIndex, DEMO_ROUNDS.length - 1)].questions.map((q, idx) => (
              <motion.div key={q.question_number} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: idx * 0.1 }} className="p-2.5 bg-[#FAF9F7] rounded-lg">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-[#111111]">{q.question_number}. {q.question_text}</span>
                  <Check className="w-3.5 h-3.5 text-green-600 flex-shrink-0" />
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      )}
    </motion.div>
  );

  const renderLiveInterview = () => {
    const showCandidate = liveSubState === "interview";
    const isDormant = liveSubState === "interview" || liveSubState === "candidate-left";
    const isOrbActive = liveSubState === "collecting" || liveSubState === "leaving";

    return (
      <motion.div key="live" initial={{ opacity: 0, x: 30 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -30 }} className="flex flex-col gap-4 h-full">
        <div className="bg-[#F2F0ED] rounded-2xl border border-[#E5E3DF] p-4 md:p-6">
          <div className={`grid gap-4 ${showCandidate ? "grid-cols-3" : "grid-cols-2"}`}>
            <div className="flex flex-col items-center gap-2 justify-center">
              <AnimatePresence mode="wait">
                {isDormant ? (
                  <motion.div key="dormant" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, scale: 0.9 }} className="w-[70px] h-[70px] md:w-[100px] md:h-[100px] rounded-xl bg-[#0a0a0a] flex flex-col items-center justify-center gap-1">
                    <svg width="24" height="24" viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">
                      <defs><path id="lp-blade" d="M 0 -12.5 L 0 -45 A 12.5 12.5 0 0 1 25 -45 L 25 -12.5 A 12.5 12.5 0 0 1 0 -12.5 Z" /></defs>
                      <g transform="translate(60, 60)">
                        <use href="#lp-blade" transform="rotate(-150) translate(0, 10)" fill="#ffffff" />
                        <use href="#lp-blade" transform="rotate(-30) translate(0, 10)" fill="#ffffff" />
                        <use href="#lp-blade" transform="rotate(90) translate(0, 10)" fill="#ffffff" />
                        <circle cx="0" cy="0" r="11" fill="#ffffff" />
                      </g>
                    </svg>
                  </motion.div>
                ) : (
                  <motion.div key="orb" initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} className="w-[70px] h-[70px] md:w-[100px] md:h-[100px]">
                    <DitheredOrb state={orbState} audioLevel={fakeAudioLevel} />
                  </motion.div>
                )}
              </AnimatePresence>
              <p className="text-xs font-semibold text-[#111111]">OpenRecruiting</p>
            </div>
            <div className="flex flex-col items-center gap-2 justify-center">
              <div className="w-[60px] h-[60px] md:w-[80px] md:h-[80px] rounded-full bg-blue-100 flex items-center justify-center">
                <span className="text-lg md:text-2xl font-bold text-blue-600">SP</span>
              </div>
              <p className="text-xs font-semibold text-[#111111]">Sarah Parker</p>
            </div>
            <AnimatePresence>
              {showCandidate && (
                <motion.div key="candidate" initial={{ opacity: 1 }} exit={{ opacity: 0, scale: 0.8 }} className="flex flex-col items-center gap-2 justify-center">
                  <div className="w-[60px] h-[60px] md:w-[80px] md:h-[80px] rounded-full bg-[#E5E3DF] flex items-center justify-center">
                    <span className="text-lg md:text-2xl font-bold text-[#555555]">JD</span>
                  </div>
                  <p className="text-xs font-semibold text-[#111111]">John Doe</p>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>

        <div className="flex items-center justify-center gap-2 py-1">
          <AnimatePresence mode="wait">
            {liveSubState === "interview" && (
              <motion.div key="s1" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex items-center gap-2">
                <span className="relative flex h-2.5 w-2.5"><span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" /><span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-red-500" /></span>
                <span className="text-xs font-medium text-[#888888]">Interview in progress</span>
              </motion.div>
            )}
            {liveSubState === "candidate-left" && (
              <motion.div key="s2" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                <span className="text-xs font-medium text-[#888888]">John Doe left the meeting</span>
              </motion.div>
            )}
            {liveSubState === "activating" && (
              <motion.div key="s3" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex items-center gap-2 text-[#888888]">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span className="text-xs font-medium">OpenRecruiting Co-pilot activating...</span>
              </motion.div>
            )}
            {liveSubState === "collecting" && (
              <motion.div key="s4" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex items-center gap-2">
                <span className="relative flex h-2.5 w-2.5"><span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" /><span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-red-500" /></span>
                <span className="text-xs font-medium text-red-600">Collecting Feedback</span>
              </motion.div>
            )}
            {liveSubState === "leaving" && (
              <motion.div key="s5" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex items-center gap-2 text-[#888888]">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span className="text-xs font-medium">OpenRecruiting Co-pilot leaving...</span>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {isOrbActive && (
          <div ref={interviewTranscriptRef} className="flex-1 max-h-[180px] overflow-y-auto space-y-2 pr-2">
            {FEEDBACK_TRANSCRIPT.slice(0, feedbackMsgCount).map((msg, i) => (
              <motion.div key={i} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className={`flex ${msg.speaker === "interviewer" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[80%] px-3 py-2 rounded-2xl text-sm ${msg.speaker === "interviewer" ? "bg-[#111111] text-white rounded-br-md" : "bg-[#F2F0ED] text-[#111111] border border-[#E5E3DF] rounded-bl-md"}`}>
                  {msg.text}
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </motion.div>
    );
  };

  const renderFeedback = () => {
    const round = DEMO_ROUNDS[0];
    return (
      <motion.div key="feedback" initial={{ opacity: 0, x: 30 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -30 }} className="h-full overflow-y-auto">
        <div className="text-center mb-4">
          <h3 className="font-display text-lg font-light text-[#111111]">Auto-Fill Feedback</h3>
          <p className="text-xs text-[#555555]">{round.name} Round · John Doe</p>
        </div>

        {/* Rating */}
        <div className="bg-white rounded-xl border border-[#E5E3DF] p-4 mb-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#888888] uppercase tracking-wide">Overall Rating</span>
            {feedbackPhase >= 1 ? (
              <motion.span initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} className={`px-3 py-1 rounded-full text-xs font-semibold ${ratingColor(round.targetRating)}`}>
                {ratingLabel(round.targetRating)}
              </motion.span>
            ) : (
              <span className="px-3 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-400">Filling...</span>
            )}
          </div>
        </div>

        {/* Overall Summary */}
        <div className="bg-white rounded-xl border border-[#E5E3DF] p-4 mb-3">
          <p className="text-xs font-medium text-[#888888] uppercase tracking-wide mb-2">Overall Summary</p>
          {feedbackPhase >= 2 ? (
            <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-sm text-[#111111] leading-relaxed">
              {round.targetSummary}
            </motion.p>
          ) : (
            <div className="space-y-1.5">
              <div className="h-3 bg-gray-100 rounded w-full animate-pulse" />
              <div className="h-3 bg-gray-100 rounded w-3/4 animate-pulse" />
            </div>
          )}
        </div>

        {/* Question Summaries */}
        <div className="space-y-2">
          {round.questions.slice(0, 2).map((q, idx) => (
            <div key={q.question_number} className="bg-white rounded-xl border border-[#E5E3DF] p-4">
              <p className="text-xs font-medium text-[#111111] mb-1">{q.question_number}. {q.question_text}</p>
              {feedbackPhase >= 3 + idx ? (
                <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-xs text-[#555555] leading-relaxed">
                  {round.targetQuestionSummaries[String(q.question_number)]}
                </motion.p>
              ) : (
                <div className="h-3 bg-gray-100 rounded w-5/6 animate-pulse" />
              )}
            </div>
          ))}
        </div>
      </motion.div>
    );
  };

  const renderPacket = () => (
    <motion.div key="packet" initial={{ opacity: 0, x: 30 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -30 }} className="h-full overflow-y-auto">
      <div className="bg-white rounded-xl border border-[#E5E3DF] p-4 mb-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-base font-bold text-[#111111]">John Doe</h3>
            <p className="text-xs text-[#555555]">Sr. Backend Engineer</p>
          </div>
          <span className="px-3 py-1 rounded-md text-xs font-semibold border border-emerald-300 text-emerald-700 bg-emerald-50/80">STRONG HIRE</span>
        </div>
        <div className="mt-2 flex items-center gap-1.5">
          <CheckCircle className="w-3 h-3 text-emerald-600" />
          <span className="text-[10px] text-[#888888]">Approved by <span className="font-medium text-[#111111]">Sarah Parker</span></span>
        </div>
      </div>
      <div className="space-y-3">
        {DEMO_ROUNDS.slice(0, visiblePacketRounds).map((round, index) => {
          const evidenceEntries = Object.entries(round.targetQuestionSummaries);
          const shownEvidence = visibleEvidence[index] || 0;
          return (
            <motion.div key={round.id} initial={{ opacity: 0, y: 15 }} animate={{ opacity: 1, y: 0 }} className="bg-white rounded-xl border border-[#E5E3DF] p-4">
              <div className="flex items-center justify-between mb-1">
                <h4 className="text-sm font-semibold text-[#111111]">Round {index + 1}: {round.name}</h4>
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${ratingColor(round.targetRating)}`}>{ratingLabel(round.targetRating)}</span>
              </div>
              <p className="text-xs text-[#555555] mb-2">{round.targetSummary}</p>
              {shownEvidence > 0 && (
                <div className="space-y-1.5 border-t border-[#E5E3DF] pt-2">
                  {evidenceEntries.slice(0, shownEvidence).map(([key, value]) => (
                    <motion.div key={key} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} className="flex items-start gap-2">
                      <Check className="w-3 h-3 text-emerald-500 mt-0.5 flex-shrink-0" />
                      <span className="text-[11px] text-[#555555] italic">{value}</span>
                    </motion.div>
                  ))}
                </div>
              )}
            </motion.div>
          );
        })}
      </div>
      {showPacketCta && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-center mt-4">
          <p className="font-display text-sm font-light text-[#111111]">Your Hiring Packet is Ready</p>
        </motion.div>
      )}
    </motion.div>
  );

  const renderAnimation = () => {
    switch (activeStep) {
      case "round-intake": return renderIntake();
      case "interview-plan": return renderPlan();
      case "live-interview": return renderLiveInterview();
      case "ai-feedback": return renderFeedback();
      case "hiring-packet": return renderPacket();
    }
  };

  return (
    <section id="from-plan-to-decision" className="py-16 md:py-24 relative overflow-hidden">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/second_home.png"
        alt=""
        className="absolute inset-0 w-full h-full object-cover z-0"
      />

      <div className="max-w-[1100px] mx-auto px-6 relative z-10">
        <h2 className="font-display text-4xl md:text-5xl font-light text-[#111111] text-center mb-4 relative z-20">
          One conversation to set up. The whole loop runs itself.
        </h2>
        <p className="text-base md:text-lg text-[#111111]/70 text-center max-w-3xl mx-auto mb-10 relative z-20">
          Roles arrive from your ATS or a voice call. OpenRecruiting builds the plan and scorecards, joins the interview, collects feedback while it is fresh, and files the packet — every step landing in Cortex as it happens. Zero new workflows.
        </p>

        {/* Glassy container */}
        <div className="rounded-3xl border border-white/20 bg-white/10 backdrop-blur-xl shadow-[0_8px_32px_rgba(0,0,0,0.2)] p-6 md:p-8">
          <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-6 lg:gap-8">
            {/* Left: Step list */}
            <div className="flex flex-row lg:flex-col gap-2 overflow-x-auto lg:overflow-visible pb-2 lg:pb-0">
              {STEP_META.map((step, index) => {
                const Icon = step.icon;
                const isActive = index === activeStepIndex;
                const isCompleted = isAutoPlaying && index < activeStepIndex;

                return (
                  <button
                    key={step.id}
                    type="button"
                    onClick={() => goToStep(step.id)}
                    className={`flex items-center gap-3 px-4 py-3 rounded-xl text-left transition-all duration-300 flex-shrink-0 cursor-pointer ${
                      isActive
                        ? "bg-[#111111] text-white shadow-lg"
                        : "bg-white/60 text-[var(--lp-text-secondary)] hover:bg-white border border-transparent"
                    }`}
                  >
                    <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
                      isActive ? "bg-white/20" : "bg-[var(--lp-surface-accent)]"
                    }`}>
                      {isCompleted ? <Check className="w-4 h-4 text-emerald-500" /> : <Icon className="w-4 h-4" />}
                    </div>
                    <div className="min-w-0 hidden lg:block">
                      <p className={`text-sm font-medium truncate ${isActive ? "text-white" : ""}`}>{step.label}</p>
                      {isActive && <p className="text-[11px] opacity-70 mt-0.5 line-clamp-2">{step.description}</p>}
                    </div>
                    <span className="lg:hidden text-xs font-medium whitespace-nowrap">{step.label}</span>
                  </button>
                );
              })}
            </div>

            {/* Right: Animation area — fixed height to prevent layout shifts */}
            <div className="flex flex-col">
              <AnimatePresence mode="wait">
                <motion.p
                  key={activeStep}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -6 }}
                  transition={{ duration: 0.25 }}
                  className="text-base md:text-lg text-[#111111]/70 text-center mb-3"
                >
                  {STEP_META[activeStepIndex]?.blurb}
                </motion.p>
              </AnimatePresence>
              <div className="h-[390px] md:h-[480px] rounded-2xl bg-[#FAF9F7] border border-[#E5E3DF] p-4 md:p-6 overflow-hidden">
                <AnimatePresence mode="wait">
                  {renderAnimation()}
                </AnimatePresence>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

export { FromPlanToDecision };
