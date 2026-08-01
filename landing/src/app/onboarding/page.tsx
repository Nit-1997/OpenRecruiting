"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { Header } from "@/components/ui/header";
import { Button } from "@/components/ui/button";
import { CalendlyModal } from "@/components/ui/calendly-modal";
import { DitheredOrb } from "@/components/ui/dithered-orb";
import { FeedbackScorecard } from "@/components/feedback/FeedbackScorecard";
import type { RatingValue, QuestionData } from "@/components/feedback/FeedbackScorecard";
import { Check, CheckCircle, Calendar, LogIn, ClipboardList, Loader2 } from "lucide-react";
import { useAnalytics } from "@/hooks/useAnalytics";

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

const STEPS = [
  { id: "round-intake", label: "Intake Call" },
  { id: "interview-plan", label: "Plan Review" },
  { id: "live-interview", label: "Interview Co-pilot" },
  { id: "ai-feedback", label: "Feedback Review" },
  { id: "hiring-packet", label: "Hiring Packet" },
];

const FEEDBACK_TRANSCRIPT = [
  { speaker: "ai", text: "Thanks Sarah. I\u2019ve captured the full interview. How would you rate John\u2019s problem-solving approach?" },
  { speaker: "interviewer", text: "Strong. He broke down the payment pipeline problem methodically and caught edge cases I didn\u2019t even prompt." },
  { speaker: "ai", text: "What about his handling of concurrent transactions?" },
  { speaker: "interviewer", text: "Impressive \u2014 the optimistic locking with event sourcing approach showed real production experience." },
  { speaker: "ai", text: "Any concerns or areas for improvement?" },
  { speaker: "interviewer", text: "He could be more concise in explanations, but technically very strong. I\u2019d say Strong Yes." },
];

const INTAKE_TRANSCRIPT = [
  { speaker: "ai", text: "Hi! I'm OpenRecruiting. Let's set up your interview process. What role are you hiring for?" },
  { speaker: "user", text: "We need a Senior Backend Engineer for our platform team." },
  { speaker: "ai", text: "Got it. What's the tech stack for this role?" },
  { speaker: "user", text: "Java 17, Spring Boot, PostgreSQL, Redis, Kafka on AWS." },
  { speaker: "ai", text: "What should they accomplish in their first 90 days?" },
  { speaker: "user", text: "Redesign our payment pipeline to cut latency by 50%." },
  { speaker: "ai", text: "Perfect. I'll generate an interview plan with 4 rounds tailored to this role." },
];

const DEMO_ROUNDS: DemoRound[] = [
  {
    id: "ps",
    name: "Problem Solving",
    roundType: "interview",
    duration: "45 mins",
    questions: [
      { question_number: 1, question_text: "Problem decomposition ability", description: "Can the candidate break down complex problems into smaller, manageable parts?" },
      { question_number: 2, question_text: "Code quality and readability", description: "Does the candidate write clean, well-structured code?" },
      { question_number: 3, question_text: "Edge case handling", description: "Does the candidate proactively identify and handle edge cases?" },
    ],
    targetRating: "strong_yes",
    targetSummary: "Excellent problem-solving skills. Broke down the payment pipeline challenge methodically, identified edge cases around concurrent transactions unprompted.",
    targetQuestionSummaries: {
      "1": "Decomposed the payment processing problem into clear modules — ingestion, validation, routing, settlement. Identified dependencies correctly.",
      "2": "Clean code with meaningful variable names. Used design patterns appropriately without over-engineering.",
      "3": "Caught race conditions in concurrent payment processing, handled currency precision issues, and addressed timeout scenarios.",
    },
  },
  {
    id: "mc",
    name: "Machine Coding",
    roundType: "assessment",
    duration: "60 mins",
    questions: [
      { question_number: 1, question_text: "Object-oriented design", description: "Does the candidate apply solid OOP principles?" },
      { question_number: 2, question_text: "Code extensibility", description: "Is the code designed for future changes and extensions?" },
      { question_number: 3, question_text: "Working demo quality", description: "Does the implementation work end-to-end with proper error handling?" },
    ],
    targetRating: "yes",
    targetSummary: "Strong implementation skills. Built a working payment gateway simulator with clean separation of concerns. Minor gaps in test coverage.",
    targetQuestionSummaries: {
      "1": "Good use of interfaces and abstract classes for payment provider abstraction. SOLID principles applied well.",
      "2": "Strategy pattern for payment providers makes adding new providers straightforward. Config-driven routing.",
      "3": "Demo worked end-to-end with Stripe and PayPal mock providers. Error handling present but could be more granular.",
    },
  },
  {
    id: "sd",
    name: "Systems Design",
    roundType: "interview",
    duration: "45 mins",
    questions: [
      { question_number: 1, question_text: "Requirements clarification", description: "Does the candidate ask the right questions before designing?" },
      { question_number: 2, question_text: "Trade-off analysis", description: "Can the candidate articulate trade-offs between different approaches?" },
      { question_number: 3, question_text: "Scalability considerations", description: "Does the design account for growth and scale?" },
    ],
    targetRating: "strong_yes",
    targetSummary: "Outstanding systems thinking. Designed a payment processing system handling 10K TPS with clear trade-off analysis between consistency and availability.",
    targetQuestionSummaries: {
      "1": "Asked about expected TPS, consistency requirements, supported currencies, and compliance needs before starting design.",
      "2": "Clearly articulated trade-offs between synchronous vs async processing, strong vs eventual consistency for different payment stages.",
      "3": "Designed with horizontal scaling in mind — stateless services, partitioned queues, read replicas for reporting.",
    },
  },
  {
    id: "bh",
    name: "Behavioural",
    roundType: "interview",
    duration: "30 mins",
    questions: [
      { question_number: 1, question_text: "Leadership examples", description: "Can the candidate demonstrate leadership in past roles?" },
      { question_number: 2, question_text: "Conflict resolution", description: "How does the candidate handle disagreements?" },
      { question_number: 3, question_text: "Communication clarity", description: "Can the candidate explain complex topics clearly?" },
    ],
    targetRating: "yes",
    targetSummary: "Good leadership signals. Led a team of 4 through a critical migration. Communicates clearly but could be more concise in explanations.",
    targetQuestionSummaries: {
      "1": "Led migration of monolith to microservices for a team of 4. Drove technical decisions and mentored 2 junior developers.",
      "2": "Handled a disagreement about database choice by running a structured proof-of-concept comparison. Data-driven resolution.",
      "3": "Explains technical concepts well, uses good analogies. Tends to over-explain — could benefit from being more concise.",
    },
  },
];

const TIMINGS = {
  TRANSCRIPT_DELAY: 900,
  ROUND_APPEAR_DELAY: 250,
  ROUND_CONFIG_DELAY: 350,
  STEP_PAUSE: 600,
};

const ratingLabel = (r: RatingValue) => {
  const map: Record<RatingValue, string> = { strong_yes: "Strong Yes", yes: "Yes", maybe: "Maybe", no: "No", strong_no: "Strong No" };
  return map[r];
};

const ratingColor = (r: RatingValue) => {
  if (r === "strong_yes" || r === "yes") return "bg-emerald-50 text-emerald-700";
  if (r === "maybe") return "bg-amber-50 text-amber-700";
  return "bg-red-50 text-red-700";
};

export default function OnboardingPage() {
  const router = useRouter();
  const { trackEvent } = useAnalytics();
  const [currentStep, setCurrentStep] = useState<DemoStep>("round-intake");

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

  // Hiring packet state
  const [visiblePacketRounds, setVisiblePacketRounds] = useState(0);
  const [showPacketCta, setShowPacketCta] = useState(false);

  // Calendly
  const [showCalendly, setShowCalendly] = useState(false);

  useEffect(() => {
    trackEvent("onboarding_demo_step_viewed", { step: currentStep });
    if (currentStep === "hiring-packet") {
      trackEvent("onboarding_demo_completed");
    }
  }, [currentStep, trackEvent]);

  const transcriptRef = useRef<HTMLDivElement>(null);
  const interviewTranscriptRef = useRef<HTMLDivElement>(null);
  const currentStepIndex = STEPS.findIndex(s => s.id === currentStep);

  useEffect(() => {
    if (orbState !== "listening") return;
    const interval = setInterval(() => {
      setFakeAudioLevel(0.3 + Math.random() * 0.6);
    }, 100);
    return () => clearInterval(interval);
  }, [orbState]);

  useEffect(() => {
    if (currentStep !== "round-intake") return;

    if (visibleMessages < INTAKE_TRANSCRIPT.length) {
      const msg = INTAKE_TRANSCRIPT[visibleMessages];
      setOrbState(msg.speaker === "user" ? "listening" : "processing");

      const timer = setTimeout(() => {
        setVisibleMessages(prev => prev + 1);
        if (transcriptRef.current) {
          transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
        }
      }, TIMINGS.TRANSCRIPT_DELAY);
      return () => clearTimeout(timer);
    } else {
      setOrbState("processing");
      const timer = setTimeout(() => {
        setOrbState("idle");
        setCurrentStep("interview-plan");
      }, TIMINGS.STEP_PAUSE);
      return () => clearTimeout(timer);
    }
  }, [currentStep, visibleMessages]);

  useEffect(() => {
    if (currentStep !== "interview-plan") return;

    if (visibleRoundsCount < DEMO_ROUNDS.length) {
      const timer = setTimeout(() => {
        setVisibleRoundsCount(prev => prev + 1);
      }, TIMINGS.ROUND_APPEAR_DELAY);
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
        setCurrentStep("live-interview");
      }, TIMINGS.STEP_PAUSE);
      return () => clearTimeout(timer);
    }
  }, [currentStep, visibleRoundsCount, configuredRoundIndex]);

  useEffect(() => {
    if (currentStep !== "live-interview") return;
    setLiveSubState("interview");
    setFeedbackMsgCount(0);
    setOrbState("idle");
  }, [currentStep]);

  useEffect(() => {
    if (currentStep !== "live-interview") return;
    let timer: ReturnType<typeof setTimeout>;

    if (liveSubState === "interview") {
      timer = setTimeout(() => setLiveSubState("candidate-left"), 1200);
    } else if (liveSubState === "candidate-left") {
      timer = setTimeout(() => setLiveSubState("activating"), 800);
    } else if (liveSubState === "activating") {
      timer = setTimeout(() => {
        setLiveSubState("collecting");
        setOrbState("listening");
      }, 1000);
    }

    return () => clearTimeout(timer);
  }, [currentStep, liveSubState]);

  useEffect(() => {
    if (currentStep !== "live-interview" || liveSubState !== "collecting") return;

    if (feedbackMsgCount < FEEDBACK_TRANSCRIPT.length) {
      const timer = setTimeout(() => {
        setFeedbackMsgCount(prev => prev + 1);
        if (interviewTranscriptRef.current) {
          interviewTranscriptRef.current.scrollTop = interviewTranscriptRef.current.scrollHeight;
        }
      }, 1000);
      return () => clearTimeout(timer);
    } else {
      setLiveSubState("leaving");
      setOrbState("processing");
    }
  }, [currentStep, liveSubState, feedbackMsgCount]);

  useEffect(() => {
    if (currentStep !== "live-interview" || liveSubState !== "leaving") return;
    const timer = setTimeout(() => setCurrentStep("ai-feedback"), 1000);
    return () => clearTimeout(timer);
  }, [currentStep, liveSubState]);

  useEffect(() => {
    if (currentStep !== "ai-feedback") return;
    const timer = setTimeout(() => setCurrentStep("hiring-packet"), 2500);
    return () => clearTimeout(timer);
  }, [currentStep]);

  useEffect(() => {
    if (currentStep !== "hiring-packet") return;
    setVisiblePacketRounds(0);
    setShowPacketCta(false);

    const timers: ReturnType<typeof setTimeout>[] = [];
    DEMO_ROUNDS.forEach((_, index) => {
      timers.push(setTimeout(() => setVisiblePacketRounds(index + 1), (index + 1) * 400));
    });
    timers.push(setTimeout(() => setShowPacketCta(true), DEMO_ROUNDS.length * 400 + 600));

    return () => timers.forEach(clearTimeout);
  }, [currentStep]);

  const handleBookDemo = () => {
    trackEvent("cta_clicked", { cta_name: "Book a Demo", cta_location: "onboarding" });
    setShowCalendly(true);
  };

  const handleExistingUserLogin = () => {
    trackEvent("cta_clicked", { cta_name: "Log in", cta_location: "onboarding" });
    router.push("/login");
  };

  const renderProgressBar = () => (
    <div id="demo-progress-bar" className="w-full bg-[#FAF9F7] border-b border-[#E5E3DF] px-6 py-4">
      <div className="max-w-4xl mx-auto">
        <div id="progress-timeline" className="relative flex justify-between items-start">
          <div id="progress-line-bg" className="absolute top-4 left-8 right-8 h-0.5 bg-[#E5E3DF]" />
          <div
            id="progress-line-active"
            className="absolute top-4 left-8 h-0.5 bg-[#111111] transition-all duration-500"
            style={{ width: `${Math.max(0, (currentStepIndex / (STEPS.length - 1)) * 100 - 8)}%` }}
          />
          {STEPS.map((step, index) => (
            <div key={step.id} id={`progress-step-${step.id}`} className="flex flex-col items-center relative z-10 w-16 sm:w-24">
              <div
                id={`progress-dot-${step.id}`}
                className={`w-8 h-8 rounded-full border-2 flex items-center justify-center transition-all duration-300 ${index < currentStepIndex
                    ? "bg-[#111111] border-[#111111]"
                    : index === currentStepIndex
                      ? "border-[#111111] bg-white"
                      : "border-[#E5E3DF] bg-white"
                  }`}
              >
                {index < currentStepIndex && <Check className="w-4 h-4 text-white" />}
                {index === currentStepIndex && <div className="w-2 h-2 rounded-full bg-[#111111]" />}
              </div>
              <p
                id={`progress-label-${step.id}`}
                className={`text-[10px] sm:text-xs mt-2 text-center ${index <= currentStepIndex ? "text-[#111111] font-medium" : "text-[#888888]"
                  }`}
              >
                {step.label}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );

  const renderRoundIntake = () => (
    <motion.div
      id="round-intake-view"
      initial={{ opacity: 0, x: 50 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -50 }}
      className="flex-1 p-6 overflow-y-auto"
    >
      <div id="intake-container" className="max-w-3xl mx-auto flex flex-col gap-4">
        <div id="intake-meeting-window" className="bg-[#F2F0ED] rounded-2xl border border-[#E5E3DF] p-6">
          <div id="intake-meeting-grid" className="grid grid-cols-2 gap-6">
            <div id="intake-orb-panel" className="flex flex-col items-center gap-3">
              <div id="intake-orb-wrapper" className="w-[120px] h-[120px] md:w-[160px] md:h-[160px]">
                <DitheredOrb state={orbState} audioLevel={fakeAudioLevel} />
              </div>
              <div id="intake-orb-label" className="text-center">
                <p id="intake-orb-name" className="text-sm font-semibold text-[#111111]">OpenRecruiting</p>
                <p id="intake-orb-role" className="text-xs text-[#888888]">Assistant</p>
              </div>
            </div>
            <div id="intake-recruiter-panel" className="flex flex-col items-center gap-3 justify-center">
              <div id="intake-recruiter-avatar" className="w-[80px] h-[80px] md:w-[110px] md:h-[110px] rounded-full bg-[#E5E3DF] flex items-center justify-center">
                <span id="intake-recruiter-initials" className="text-2xl md:text-3xl font-bold text-[#555555]">You</span>
              </div>
              <div id="intake-recruiter-label" className="text-center">
                <p id="intake-recruiter-name" className="text-sm font-semibold text-[#111111]">Recruiter</p>
                <p id="intake-recruiter-role" className="text-xs text-[#888888]">You</p>
              </div>
            </div>
          </div>
        </div>

        <div
          id="intake-transcript"
          ref={transcriptRef}
          className="max-h-[260px] overflow-y-auto space-y-3 pr-2"
        >
          {INTAKE_TRANSCRIPT.slice(0, visibleMessages).map((msg, index) => (
            <motion.div
              key={index}
              id={`intake-msg-${index}`}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              className={`flex ${msg.speaker === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                id={`intake-bubble-${index}`}
                className={`max-w-[80%] px-4 py-3 rounded-2xl text-sm ${
                  msg.speaker === "user"
                    ? "bg-[#111111] text-white rounded-br-md"
                    : "bg-[#F2F0ED] text-[#111111] border border-[#E5E3DF] rounded-bl-md"
                }`}
              >
                {msg.text}
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </motion.div>
  );

  const renderInterviewPlan = () => (
    <motion.div
      id="interview-plan-view"
      initial={{ opacity: 0, x: 50 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -50 }}
      className="flex-1 flex flex-col lg:flex-row min-h-0"
    >
      <div id="rounds-mobile-pills" className="flex lg:hidden gap-2 px-4 py-3 overflow-x-auto border-b border-[#E5E3DF] bg-[#FAF9F7]">
        {DEMO_ROUNDS.slice(0, visibleRoundsCount).map((round, index) => (
          <button
            key={round.id}
            id={`mobile-plan-pill-${round.id}`}
            type="button"
            onClick={() => setSelectedRoundIndex(index)}
            className={`flex-shrink-0 px-4 py-2 rounded-full text-sm font-medium transition-all cursor-pointer ${
              index === selectedRoundIndex
                ? "bg-primary text-primary-foreground"
                : index <= configuredRoundIndex
                  ? "bg-primary/10 text-primary"
                  : "bg-secondary/50 text-muted-foreground"
            }`}
          >
            {round.name}
          </button>
        ))}
      </div>

      <aside id="rounds-sidebar" className="hidden lg:block w-72 border-r border-[#E5E3DF] bg-white p-5 overflow-y-auto">
        <h3 id="sidebar-title" className="font-mono-label text-xs tracking-wider uppercase text-[#888888] mb-4">INTERVIEW ROUNDS</h3>
        <div id="sidebar-rounds" className="relative pl-8">
          <div id="sidebar-timeline-line" className="absolute left-[13px] top-3 bottom-4 w-0.5 bg-[#E5E3DF]" />
          <div className="space-y-10">
            {DEMO_ROUNDS.slice(0, visibleRoundsCount).map((round, index) => (
              <motion.div
                key={round.id}
                id={`sidebar-round-${round.id}`}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                className="relative cursor-pointer"
                onClick={() => setSelectedRoundIndex(index)}
              >
                <div
                  id={`sidebar-dot-${round.id}`}
                  className={`absolute -left-8 top-1 w-6 h-6 rounded-full border-2 flex items-center justify-center bg-white transition-all ${
                    index <= configuredRoundIndex
                      ? "border-green-500 bg-green-500"
                      : index === selectedRoundIndex
                        ? round.roundType === "assessment" ? "border-amber-500" : "border-[#111111]"
                        : "border-[#E5E3DF]"
                  }`}
                >
                  {index <= configuredRoundIndex ? (
                    <Check className="w-3 h-3 text-white" />
                  ) : round.roundType === "assessment" ? (
                    <ClipboardList className={`w-3 h-3 ${index === selectedRoundIndex ? "text-amber-500" : "text-amber-400"}`} />
                  ) : null}
                </div>
                <div className="flex items-center gap-2">
                  <p className={`text-sm ${index === selectedRoundIndex ? "text-[#111111] font-medium" : "text-[#888888]"}`}>
                    Round {index + 1}
                  </p>
                  {round.roundType === "assessment" ? (
                    <span id={`sidebar-badge-${round.id}`} className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">
                      Assessment
                    </span>
                  ) : (
                    <span id={`sidebar-badge-${round.id}`} className="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 text-blue-700">
                      Interview
                    </span>
                  )}
                </div>
                <p className={`font-semibold ${index === selectedRoundIndex ? "text-[#111111]" : "text-[#888888]"}`}>
                  {round.name}
                </p>
                <p className="text-xs text-[#888888] mt-1">{round.duration}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </aside>

      <main id="plan-main" className="flex-1 bg-[#FAF9F7] p-6 overflow-y-auto">
        {configuredRoundIndex >= 0 && (
          <div id="round-config-card" className="bg-white rounded-2xl border border-[#E5E3DF] p-6">
            <div id="config-header" className="flex items-center justify-between mb-6">
              <h2 id="config-title" className="text-xl font-bold">
                Configuring: {DEMO_ROUNDS[Math.min(configuredRoundIndex, DEMO_ROUNDS.length - 1)].name}
              </h2>
              <span id="config-duration" className="px-3 py-1 text-sm border border-orange-400 text-orange-600 rounded-lg bg-orange-50">
                {DEMO_ROUNDS[Math.min(configuredRoundIndex, DEMO_ROUNDS.length - 1)].duration}
              </span>
            </div>
            <div id="config-questions" className="space-y-3">
              {DEMO_ROUNDS[Math.min(configuredRoundIndex, DEMO_ROUNDS.length - 1)].questions.map((q, idx) => (
                <motion.div
                  key={q.question_number}
                  id={`config-question-${q.question_number}`}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: idx * 0.1 }}
                  className="p-4 bg-secondary/30 rounded-lg"
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-medium">{q.question_number}. {q.question_text}</span>
                    <Check className="w-4 h-4 text-primary flex-shrink-0" />
                  </div>
                  {q.description && (
                    <p className="text-xs text-muted-foreground">{q.description}</p>
                  )}
                </motion.div>
              ))}
            </div>
          </div>
        )}
      </main>
    </motion.div>
  );

  const renderLiveInterview = () => {
    const showCandidate = liveSubState === "interview";
    const isDormant = liveSubState === "interview" || liveSubState === "candidate-left";
    const isOrbActive = liveSubState === "collecting" || liveSubState === "leaving";

    return (
      <motion.div
        id="live-interview-view"
        key="live-interview"
        initial={{ opacity: 0, x: 50 }}
        animate={{ opacity: 1, x: 0 }}
        exit={{ opacity: 0, x: -50 }}
        className="flex-1 p-6 overflow-y-auto"
      >
        <div id="live-interview-container" className="max-w-3xl mx-auto flex flex-col gap-4">
          <div id="live-meeting-window" className="bg-[#F2F0ED] rounded-2xl border border-[#E5E3DF] p-6">
            <div id="live-meeting-grid" className={`grid gap-4 md:gap-6 ${showCandidate ? "grid-cols-3" : "grid-cols-2"}`}>
              <div id="live-scout-panel" className="flex flex-col items-center gap-2 justify-center">
                <AnimatePresence mode="wait">
                  {isDormant ? (
                    <motion.div
                      id="live-dormant-tile"
                      key="dormant"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0, scale: 0.9 }}
                      transition={{ duration: 0.5 }}
                      className="w-[80px] h-[80px] md:w-[120px] md:h-[120px] rounded-xl bg-[#0a0a0a] flex flex-col items-center justify-center gap-1.5"
                    >
                      <svg id="live-dormant-logo" width="32" height="32" viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">
                        <defs><path id="demo-blade" d="M 0 -12.5 L 0 -45 A 12.5 12.5 0 0 1 25 -45 L 25 -12.5 A 12.5 12.5 0 0 1 0 -12.5 Z" /></defs>
                        <g transform="translate(60, 60)">
                          <use href="#demo-blade" transform="rotate(-150) translate(0, 10)" fill="#ffffff" />
                          <use href="#demo-blade" transform="rotate(-30) translate(0, 10)" fill="#ffffff" />
                          <use href="#demo-blade" transform="rotate(90) translate(0, 10)" fill="#ffffff" />
                          <circle cx="0" cy="0" r="11" fill="#ffffff" />
                        </g>
                      </svg>
                      <div id="live-dormant-wordmark" className="flex items-baseline">
                        <span className="text-[10px] md:text-xs text-neutral-300" style={{ fontStyle: "italic" }}>openrecruiting</span>
                        <span className="text-[10px] md:text-xs text-neutral-500" style={{ fontStyle: "italic" }}>.ai</span>
                      </div>
                    </motion.div>
                  ) : (
                    <motion.div
                      id="live-orb-active-tile"
                      key="orb"
                      initial={{ opacity: 0, scale: 0.8 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ duration: 0.6 }}
                      className="w-[80px] h-[80px] md:w-[120px] md:h-[120px]"
                    >
                      <DitheredOrb state={orbState} audioLevel={fakeAudioLevel} />
                    </motion.div>
                  )}
                </AnimatePresence>
                <div id="live-scout-label" className="text-center">
                  <p id="live-scout-name" className="text-xs md:text-sm font-semibold text-[#111111]">OpenRecruiting</p>
                  <p id="live-scout-role" className="text-[10px] md:text-xs text-[#888888]">
                    {isDormant ? "Recording" : "Co-pilot"}
                  </p>
                </div>
              </div>
              <div id="live-interviewer-panel" className="flex flex-col items-center gap-2 justify-center">
                <div id="live-interviewer-avatar" className="w-[70px] h-[70px] md:w-[100px] md:h-[100px] rounded-full bg-blue-100 flex items-center justify-center">
                  <span id="live-interviewer-initials" className="text-xl md:text-3xl font-bold text-blue-600">SP</span>
                </div>
                <div id="live-interviewer-label" className="text-center">
                  <p id="live-interviewer-name" className="text-xs md:text-sm font-semibold text-[#111111]">Sarah Parker</p>
                  <p id="live-interviewer-role" className="text-[10px] md:text-xs text-[#888888]">Interviewer</p>
                </div>
              </div>
              <AnimatePresence>
                {showCandidate && (
                  <motion.div
                    id="live-candidate-panel"
                    key="candidate"
                    initial={{ opacity: 1 }}
                    exit={{ opacity: 0, scale: 0.8, y: 10 }}
                    transition={{ duration: 0.5 }}
                    className="flex flex-col items-center gap-2 justify-center"
                  >
                    <div id="live-candidate-avatar" className="w-[70px] h-[70px] md:w-[100px] md:h-[100px] rounded-full bg-[#E5E3DF] flex items-center justify-center">
                      <span id="live-candidate-initials" className="text-xl md:text-3xl font-bold text-[#555555]">JD</span>
                    </div>
                    <div id="live-candidate-label" className="text-center">
                      <p id="live-candidate-name" className="text-xs md:text-sm font-semibold text-[#111111]">John Doe</p>
                      <p id="live-candidate-role" className="text-[10px] md:text-xs text-[#888888]">Candidate</p>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>

          <div id="live-status-bar" className="flex items-center justify-center gap-2 py-2">
            <AnimatePresence mode="wait">
              {liveSubState === "interview" && (
                <motion.div
                  id="live-status-interview"
                  key="interview"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.3 }}
                  className="flex items-center gap-2"
                >
                  <span id="live-interview-dot" className="relative flex h-2.5 w-2.5">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-red-500" />
                  </span>
                  <span id="live-interview-text" className="text-sm font-medium text-muted-foreground">Interview in progress</span>
                </motion.div>
              )}
              {liveSubState === "candidate-left" && (
                <motion.div
                  id="live-status-candidate-left"
                  key="candidate-left"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.3 }}
                  className="flex items-center gap-2 text-muted-foreground"
                >
                  <span id="live-candidate-left-text" className="text-sm font-medium">John Doe left the meeting</span>
                </motion.div>
              )}
              {liveSubState === "activating" && (
                <motion.div
                  id="live-status-activating"
                  key="activating"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.3 }}
                  className="flex items-center gap-2 text-muted-foreground"
                >
                  <Loader2 id="live-activating-spinner" className="w-4 h-4 animate-spin" />
                  <span id="live-activating-text" className="text-sm font-medium">OpenRecruiting Co-pilot activating...</span>
                </motion.div>
              )}
              {liveSubState === "collecting" && (
                <motion.div
                  id="live-status-collecting"
                  key="collecting"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.3 }}
                  className="flex items-center gap-2"
                >
                  <span id="live-collecting-dot" className="relative flex h-3 w-3">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-3 w-3 bg-red-500" />
                  </span>
                  <span id="live-collecting-text" className="text-sm font-medium text-red-600">Collecting Feedback</span>
                </motion.div>
              )}
              {liveSubState === "leaving" && (
                <motion.div
                  id="live-status-leaving"
                  key="leaving"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.3 }}
                  className="flex items-center gap-2 text-muted-foreground"
                >
                  <Loader2 id="live-leaving-spinner" className="w-4 h-4 animate-spin" />
                  <span id="live-leaving-text" className="text-sm font-medium">OpenRecruiting Co-pilot leaving meeting...</span>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {isOrbActive && (
            <div
              id="live-feedback-transcript"
              ref={interviewTranscriptRef}
              className="max-h-[240px] overflow-y-auto space-y-3 pr-2"
            >
              {FEEDBACK_TRANSCRIPT.slice(0, feedbackMsgCount).map((msg, index) => (
                <motion.div
                  key={index}
                  id={`feedback-msg-${index}`}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={`flex ${msg.speaker === "interviewer" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    id={`feedback-bubble-${index}`}
                    className={`max-w-[80%] px-4 py-3 rounded-2xl text-sm ${
                      msg.speaker === "interviewer"
                        ? "bg-[#111111] text-white rounded-br-md"
                        : "bg-[#F2F0ED] text-[#111111] border border-[#E5E3DF] rounded-bl-md"
                    }`}
                  >
                    {msg.text}
                  </div>
                </motion.div>
              ))}
            </div>
          )}
        </div>
      </motion.div>
    );
  };

  const renderAiFeedback = () => {
    const round = DEMO_ROUNDS[0];

    return (
      <motion.div
        id="ai-feedback-view"
        key="ai-feedback"
        initial={{ opacity: 0, x: 50 }}
        animate={{ opacity: 1, x: 0 }}
        exit={{ opacity: 0, x: -50 }}
        className="flex-1 p-6 overflow-y-auto"
      >
        <div className="max-w-2xl mx-auto">
          <div id="feedback-review-header" className="text-center mb-6">
            <h2 id="feedback-review-title" className="font-display text-2xl font-light text-[#111111]">Feedback Review</h2>
            <p id="feedback-review-subtitle" className="text-[#555555] mt-1">{round.name} Round &middot; John Doe</p>
          </div>
          <div id="feedback-review-scorecard-wrapper">
            <FeedbackScorecard
              candidateName="John Doe"
              roundName={round.name}
              rating={round.targetRating}
              summary={round.targetSummary}
              questions={round.questions}
              questionSummaries={round.targetQuestionSummaries}
              mode="interactive"
              hideEditMode
            />
          </div>
          <div id="feedback-review-actions" className="mt-6 flex justify-center">
            <Button
              id="feedback-approve-btn"
              size="lg"
              className="gap-2 px-8"
              onClick={() => setCurrentStep("hiring-packet")}
            >
              <CheckCircle className="w-5 h-5" />
              Approve & Done
            </Button>
          </div>
        </div>
      </motion.div>
    );
  };

  const renderHiringPacket = () => (
    <motion.div
      id="hiring-packet-view"
      key="hiring-packet"
      initial={{ opacity: 0, x: 50 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -50 }}
      className="flex-1 p-6 overflow-y-auto"
    >
      <div className="max-w-3xl mx-auto">
        <div id="packet-candidate-header" className="bg-white rounded-2xl border border-[#E5E3DF] p-6 mb-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 id="packet-candidate-name" className="text-xl font-bold">John Doe</h2>
              <p id="packet-candidate-role" className="text-[#555555] text-sm">Sr. Backend Engineer</p>
            </div>
            <span
              id="packet-verdict-badge"
              className="inline-block px-4 py-1.5 rounded-md text-sm font-semibold tracking-wide border border-emerald-300 text-emerald-700 bg-emerald-50/80"
            >
              STRONG HIRE
            </span>
          </div>
          <div id="packet-approved-pill" className="mt-3 flex items-center gap-1.5">
            <CheckCircle className="w-3.5 h-3.5 text-emerald-600" />
            <span className="text-xs text-[#888888]">Approved by <span className="font-medium text-[#111111]">Sarah Parker</span></span>
          </div>
        </div>

        <div id="packet-rounds-list" className="space-y-4 mb-8">
          {DEMO_ROUNDS.slice(0, visiblePacketRounds).map((round, index) => (
            <motion.div
              key={round.id}
              id={`packet-round-${round.id}`}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.15 }}
              className="bg-white rounded-xl border border-[#E5E3DF] p-5"
            >
              <div className="flex items-center justify-between mb-2">
                <h3 id={`packet-round-name-${round.id}`} className="font-semibold">
                  Round {index + 1}: {round.name}
                </h3>
                <span
                  id={`packet-round-rating-${round.id}`}
                  className={`px-2.5 py-1 rounded-full text-xs font-medium ${ratingColor(round.targetRating)}`}
                >
                  {ratingLabel(round.targetRating)}
                </span>
              </div>
              <p id={`packet-round-summary-${round.id}`} className="text-sm text-[#555555]">
                {round.targetSummary}
              </p>
            </motion.div>
          ))}
        </div>

        {showPacketCta && (
          <motion.div
            id="packet-cta-section"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-center space-y-4"
          >
            <h3 id="packet-cta-title" className="font-display text-xl font-light text-[#111111]">Your Hiring Packet is Ready</h3>
            <p id="packet-cta-subtitle" className="text-[#555555]">Try OpenRecruiting Today</p>
            <Button
              id="packet-book-demo-btn"
              size="lg"
              className="bg-[#111111] text-white hover:bg-[#111111]/90 rounded-full px-10 h-14 text-lg gap-2"
              onClick={handleBookDemo}
            >
              <Calendar className="w-5 h-5" />
              Book a Demo
            </Button>
            <p id="packet-login-text" className="text-sm text-[#555555]">
              Already have an account?{" "}
              <button
                id="packet-login-link"
                type="button"
                onClick={handleExistingUserLogin}
                className="text-primary hover:underline font-medium cursor-pointer"
              >
                Log in
              </button>
            </p>
          </motion.div>
        )}
      </div>
    </motion.div>
  );

  const renderStepContent = () => {
    switch (currentStep) {
      case "round-intake":
        return renderRoundIntake();
      case "interview-plan":
        return renderInterviewPlan();
      case "live-interview":
        return renderLiveInterview();
      case "ai-feedback":
        return renderAiFeedback();
      case "hiring-packet":
        return renderHiringPacket();
      default:
        return null;
    }
  };

  return (
    <div id="onboarding-page" className="h-screen flex flex-col">
      <Header variant="light" />
      <div id="onboarding-header-spacer" className="h-16 xl:h-20 flex-shrink-0" />
      {renderProgressBar()}
      <div id="demo-content" className="flex-1 flex flex-col bg-[#FAF9F7] min-h-0">
        <AnimatePresence mode="wait">
          {renderStepContent()}
        </AnimatePresence>
      </div>

      <CalendlyModal
        isOpen={showCalendly}
        onClose={() => setShowCalendly(false)}
      />
    </div>
  );
}
