"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import {
  Building2,
  ArrowLeft,
  Check,
  Plus,
  X,
  Pencil,
  Trash2,
  Star,
  ChevronRight,
  MapPin,
  Briefcase,
  LogOut,
} from "lucide-react";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { AuthGuard } from "@/components/auth-guard";

type Step = "basic-info" | "intake-notes" | "interview-plan" | "confirmation";

interface Customer {
  id: string;
  name: string;
  email: string;
  company: string;
  createdAt: string;
  requisitionCount: number;
}

interface Guideline {
  id: string;
  title: string;
  description: string;
}

interface ScoreCriterion {
  id: string;
  description: string;
  stars: number;
  feedback: string;
}

interface Round {
  id: string;
  name: string;
  category: "coding" | "design" | "behavioural";
  duration: string;
  description: string;
  skills: string[];
  scoreCriteria: ScoreCriterion[];
  guidelines: Guideline[];
}

const STEPS = [
  { id: "basic-info", label: "Role Info" },
  { id: "intake-notes", label: "Intake Notes" },
  { id: "interview-plan", label: "Interview Plan" },
  { id: "confirmation", label: "Confirmation" },
];

const roundDescriptions: Record<string, string> = {
  "Problem Solving": "A coding interview round is usually 30-45 minutes where you solve 1-2 problems involving data structures and algorithms. The interviewer presents a problem you clarify requirements, propose an approach, and then implement the solution while explaining your thinking. You are expected to analyze complexity, handle edge cases, and test your code with sample inputs.",
  "Machine Coding": "A machine coding round is typically 60-90 minutes where you implement a working solution for a real-world problem. You'll design classes, write clean code, and handle requirements that may evolve. Focus is on object-oriented design, code organization, and building extensible solutions.",
  "Systems Design": "A systems design round is usually 45-60 minutes where you architect a large-scale distributed system. You'll discuss requirements, propose high-level architecture, dive into component design, and address scalability, reliability, and trade-offs.",
  "Behavioural": "A behavioural round is typically 30-45 minutes where you discuss past experiences, leadership scenarios, and how you handle challenges. Focus is on communication, ownership, conflict resolution, and cultural fit.",
};

const roundSkills: Record<string, string[]> = {
  "Problem Solving": ["Data Structures", "Algorithms", "Problem Decomposition", "Code Quality", "Java", "Python"],
  "Machine Coding": ["OOPS", "Design Patterns", "Clean Code", "Unit Testing", "Java", "Python"],
  "Systems Design": ["Distributed Systems", "Scalability", "Database Design", "Caching", "Load Balancing"],
  "Behavioural": ["Leadership", "Communication", "Conflict Resolution", "Ownership", "Teamwork"],
};

const roundGuidelines: Record<string, Guideline[]> = {
  "Problem Solving": [
    { id: "ps-g1", title: "Understand the Problem", description: "Ask clarifying questions about input/output formats, constraints, and edge cases before coding." },
    { id: "ps-g2", title: "Discuss Approach", description: "Explain your thought process and proposed algorithm before implementation." },
    { id: "ps-g3", title: "Analyze Complexity", description: "Discuss time and space complexity of your solution." },
    { id: "ps-g4", title: "Write Clean Code", description: "Use meaningful variable names, proper indentation, and modular functions." },
    { id: "ps-g5", title: "Test Your Solution", description: "Walk through test cases including edge cases to verify correctness." },
  ],
  "Machine Coding": [
    { id: "mc-g1", title: "Gather Requirements", description: "Clarify functional requirements and identify core use cases before designing." },
    { id: "mc-g2", title: "Design Classes", description: "Identify key entities, their attributes, and relationships using OOP principles." },
    { id: "mc-g3", title: "Handle Extensions", description: "Design for extensibility - the requirements may evolve during the round." },
    { id: "mc-g4", title: "Write Modular Code", description: "Separate concerns, use interfaces, and follow SOLID principles." },
    { id: "mc-g5", title: "Demonstrate Working Code", description: "Show a working demo with proper input/output handling." },
  ],
  "Systems Design": [
    { id: "sd-g1", title: "Clarify Requirements", description: "Clarify functional and non-functional requirements (scale, latency, availability)." },
    { id: "sd-g2", title: "Capacity Estimates", description: "Do rough capacity estimates: users, QPS, read/write ratio, data size." },
    { id: "sd-g3", title: "High-Level Architecture", description: "Propose architecture: clients, load balancers, services, databases, caches." },
    { id: "sd-g4", title: "Data Model", description: "Design data model: entities, relationships, indexing, SQL vs NoSQL." },
    { id: "sd-g5", title: "Scaling & Reliability", description: "Discuss sharding, replication, caching, failover, and fault tolerance." },
  ],
  "Behavioural": [
    { id: "bh-g1", title: "Use STAR Method", description: "Structure answers with Situation, Task, Action, and Result." },
    { id: "bh-g2", title: "Show Ownership", description: "Demonstrate taking responsibility and driving outcomes." },
    { id: "bh-g3", title: "Highlight Collaboration", description: "Share examples of working effectively with teams." },
    { id: "bh-g4", title: "Discuss Challenges", description: "Talk about how you handled conflicts, failures, or difficult situations." },
  ],
};

const generateInitialRounds = (): Round[] => [
  {
    id: "round-1",
    name: "Problem Solving",
    category: "coding",
    duration: "45 mins",
    description: roundDescriptions["Problem Solving"],
    skills: roundSkills["Problem Solving"],
    guidelines: roundGuidelines["Problem Solving"],
    scoreCriteria: [
      { id: "ps-1", description: "Rate Candidate's problem decomposition and approach", stars: 0, feedback: "" },
      { id: "ps-2", description: "Rate Candidate's code quality and readability", stars: 0, feedback: "" },
      { id: "ps-3", description: "Rate Candidate's edge case handling", stars: 0, feedback: "" },
      { id: "ps-4", description: "Rate Candidate's overall communication", stars: 0, feedback: "" },
    ],
  },
  {
    id: "round-2",
    name: "Machine Coding",
    category: "coding",
    duration: "60 mins",
    description: roundDescriptions["Machine Coding"],
    skills: roundSkills["Machine Coding"],
    guidelines: roundGuidelines["Machine Coding"],
    scoreCriteria: [
      { id: "mc-1", description: "Rate Candidate's ability to identify and clarify requirements", stars: 0, feedback: "" },
      { id: "mc-2", description: "Rate Candidate's Object Oriented Design skills", stars: 0, feedback: "" },
      { id: "mc-3", description: "Rate Candidate's ability to adapt to changing requirements", stars: 0, feedback: "" },
      { id: "mc-4", description: "Rate Candidate's working demo quality", stars: 0, feedback: "" },
    ],
  },
  {
    id: "round-3",
    name: "Systems Design",
    category: "design",
    duration: "45 mins",
    description: roundDescriptions["Systems Design"],
    skills: roundSkills["Systems Design"],
    guidelines: roundGuidelines["Systems Design"],
    scoreCriteria: [
      { id: "sd-1", description: "Rate Candidate's requirements clarification ability", stars: 0, feedback: "" },
      { id: "sd-2", description: "Rate Candidate's architecture quality", stars: 0, feedback: "" },
      { id: "sd-3", description: "Rate Candidate's trade-off analysis skills", stars: 0, feedback: "" },
      { id: "sd-4", description: "Rate Candidate's scalability considerations", stars: 0, feedback: "" },
    ],
  },
  {
    id: "round-4",
    name: "Behavioural",
    category: "behavioural",
    duration: "30 mins",
    description: roundDescriptions["Behavioural"],
    skills: roundSkills["Behavioural"],
    guidelines: roundGuidelines["Behavioural"],
    scoreCriteria: [
      { id: "bh-1", description: "Rate Candidate's Leadership attributes", stars: 0, feedback: "" },
      { id: "bh-2", description: "Rate Candidate's Conflict Resolution skills", stars: 0, feedback: "" },
      { id: "bh-3", description: "Rate Candidate's achievements and ownership", stars: 0, feedback: "" },
      { id: "bh-4", description: "Rate Candidate's overall communication", stars: 0, feedback: "" },
    ],
  },
];

export default function NewRequisitionPage() {
  const params = useParams();
  const router = useRouter();
  const customerId = params.customerId as string;

  const [customer, setCustomer] = useState<Customer | null>(null);
  const [currentStep, setCurrentStep] = useState<Step>("basic-info");

  const [roleTitle, setRoleTitle] = useState("");
  const [level, setLevel] = useState("");
  const [location, setLocation] = useState("");

  const [jobDescription, setJobDescription] = useState("");
  const [mustHaveSkills, setMustHaveSkills] = useState<string[]>([]);
  const [goodToHaveSkills, setGoodToHaveSkills] = useState<string[]>([]);
  const [intakeNotes, setIntakeNotes] = useState("");
  const [newMustHave, setNewMustHave] = useState("");
  const [newGoodToHave, setNewGoodToHave] = useState("");

  const [rounds, setRounds] = useState<Round[]>(generateInitialRounds());
  const [selectedRoundIndex, setSelectedRoundIndex] = useState(0);
  const [editingCriterionId, setEditingCriterionId] = useState<string | null>(null);
  const [showDetailsPopup, setShowDetailsPopup] = useState(false);
  const [showGuidelinesPopup, setShowGuidelinesPopup] = useState(false);
  const [expandedRound, setExpandedRound] = useState<string | null>(null);
  const [newSkill, setNewSkill] = useState("");
  const [newGuidelineTitle, setNewGuidelineTitle] = useState("");
  const [newGuidelineDesc, setNewGuidelineDesc] = useState("");

  const currentStepIndex = STEPS.findIndex(s => s.id === currentStep);

  const handleLogout = () => {
    localStorage.removeItem("admin_auth");
    router.push("/login");
  };

  useEffect(() => {
    const storedCustomers = JSON.parse(localStorage.getItem("admin_customers") || "[]");
    const foundCustomer = storedCustomers.find((c: Customer) => c.id === customerId);
    setCustomer(foundCustomer || null);
  }, [customerId]);

  const handleAddMustHave = () => {
    if (newMustHave.trim() && !mustHaveSkills.includes(newMustHave.trim())) {
      setMustHaveSkills([...mustHaveSkills, newMustHave.trim()]);
      setNewMustHave("");
    }
  };

  const handleAddGoodToHave = () => {
    if (newGoodToHave.trim() && !goodToHaveSkills.includes(newGoodToHave.trim())) {
      setGoodToHaveSkills([...goodToHaveSkills, newGoodToHave.trim()]);
      setNewGoodToHave("");
    }
  };

  const addCriterion = (roundId: string) => {
    setRounds(prev => prev.map(r => {
      if (r.id === roundId) {
        return {
          ...r,
          scoreCriteria: [
            ...r.scoreCriteria,
            { id: `criterion-${Date.now()}`, description: "New evaluation criterion", stars: 0, feedback: "" },
          ],
        };
      }
      return r;
    }));
  };

  const removeCriterion = (roundId: string, criterionId: string) => {
    setRounds(prev => prev.map(r => {
      if (r.id === roundId) {
        return { ...r, scoreCriteria: r.scoreCriteria.filter(c => c.id !== criterionId) };
      }
      return r;
    }));
  };

  const updateCriterionDescription = (roundId: string, criterionId: string, description: string) => {
    setRounds(prev => prev.map(r => {
      if (r.id === roundId) {
        return {
          ...r,
          scoreCriteria: r.scoreCriteria.map(c => c.id === criterionId ? { ...c, description } : c),
        };
      }
      return r;
    }));
  };

  const updateCriterionStars = (roundId: string, criterionId: string, stars: number) => {
    setRounds(prev => prev.map(r => {
      if (r.id === roundId) {
        return {
          ...r,
          scoreCriteria: r.scoreCriteria.map(c => c.id === criterionId ? { ...c, stars } : c),
        };
      }
      return r;
    }));
  };

  const updateCriterionFeedback = (roundId: string, criterionId: string, feedback: string) => {
    setRounds(prev => prev.map(r => {
      if (r.id === roundId) {
        return {
          ...r,
          scoreCriteria: r.scoreCriteria.map(c => c.id === criterionId ? { ...c, feedback } : c),
        };
      }
      return r;
    }));
  };

  const addRound = () => {
    const newRound: Round = {
      id: `round-${Date.now()}`,
      name: "New Round",
      category: "coding",
      duration: "45 mins",
      description: "A new interview round to evaluate candidates.",
      skills: ["Technical Skills"],
      guidelines: [{ id: `g-${Date.now()}`, title: "Guideline 1", description: "Add your evaluation guideline here." }],
      scoreCriteria: [{ id: `criterion-${Date.now()}`, description: "Rate Candidate's technical skills", stars: 0, feedback: "" }],
    };
    setRounds(prev => [...prev, newRound]);
    setSelectedRoundIndex(rounds.length);
  };

  const deleteRound = (roundId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (rounds.length <= 1) return;
    const roundIndex = rounds.findIndex(r => r.id === roundId);
    setRounds(prev => prev.filter(r => r.id !== roundId));
    if (selectedRoundIndex >= roundIndex && selectedRoundIndex > 0) {
      setSelectedRoundIndex(selectedRoundIndex - 1);
    }
  };

  const updateRoundName = (roundId: string, name: string) => {
    setRounds(prev => prev.map(r => r.id === roundId ? { ...r, name } : r));
  };

  const updateRoundDescription = (roundId: string, description: string) => {
    setRounds(prev => prev.map(r => r.id === roundId ? { ...r, description } : r));
  };

  const addSkill = (roundId: string) => {
    if (!newSkill.trim()) return;
    setRounds(prev => prev.map(r => {
      if (r.id === roundId) {
        return { ...r, skills: [...r.skills, newSkill.trim()] };
      }
      return r;
    }));
    setNewSkill("");
  };

  const removeSkill = (roundId: string, skillIndex: number) => {
    setRounds(prev => prev.map(r => {
      if (r.id === roundId) {
        return { ...r, skills: r.skills.filter((_, idx) => idx !== skillIndex) };
      }
      return r;
    }));
  };

  const updateGuideline = (roundId: string, guidelineId: string, field: "title" | "description", value: string) => {
    setRounds(prev => prev.map(r => {
      if (r.id === roundId) {
        return {
          ...r,
          guidelines: r.guidelines.map(g => g.id === guidelineId ? { ...g, [field]: value } : g)
        };
      }
      return r;
    }));
  };

  const addGuideline = (roundId: string) => {
    if (!newGuidelineTitle.trim()) return;
    const newGuideline: Guideline = {
      id: `guideline-${Date.now()}`,
      title: newGuidelineTitle.trim(),
      description: newGuidelineDesc.trim(),
    };
    setRounds(prev => prev.map(r => {
      if (r.id === roundId) {
        return { ...r, guidelines: [...r.guidelines, newGuideline] };
      }
      return r;
    }));
    setNewGuidelineTitle("");
    setNewGuidelineDesc("");
  };

  const removeGuideline = (roundId: string, guidelineId: string) => {
    setRounds(prev => prev.map(r => {
      if (r.id === roundId) {
        return { ...r, guidelines: r.guidelines.filter(g => g.id !== guidelineId) };
      }
      return r;
    }));
  };

  const handleNext = () => {
    if (currentStep === "basic-info") {
      if (!roleTitle.trim()) return;
      setCurrentStep("intake-notes");
    } else if (currentStep === "intake-notes") {
      setCurrentStep("interview-plan");
    } else if (currentStep === "interview-plan") {
      setCurrentStep("confirmation");
    }
  };

  const handleBack = () => {
    if (currentStep === "intake-notes") {
      setCurrentStep("basic-info");
    } else if (currentStep === "interview-plan") {
      setCurrentStep("intake-notes");
    } else if (currentStep === "confirmation") {
      setCurrentStep("interview-plan");
    }
  };

  const handleSave = () => {
    if (!customer) return;

    const newReq = {
      id: `req_${Date.now()}`,
      customerId: customer.id,
      customerName: customer.name,
      roleTitle: roleTitle.trim(),
      level,
      location,
      status: "plan_ready" as const,
      createdAt: new Date().toISOString(),
      jobDescription,
      mustHaveSkills,
      goodToHaveSkills,
      intakeNotes,
      interviewPlan: rounds,
    };

    const allRequisitions = JSON.parse(localStorage.getItem("admin_requisitions") || "[]");
    localStorage.setItem("admin_requisitions", JSON.stringify([...allRequisitions, newReq]));

    const allCustomers = JSON.parse(localStorage.getItem("admin_customers") || "[]");
    const updatedCustomers = allCustomers.map((c: Customer) =>
      c.id === customer.id ? { ...c, requisitionCount: c.requisitionCount + 1 } : c
    );
    localStorage.setItem("admin_customers", JSON.stringify(updatedCustomers));

    router.push(`/customers/${customer.id}`);
  };

  const selectedRound = rounds[selectedRoundIndex];

  const renderStarRating = (criterionId: string, currentStars: number) => {
    return (
      <div id={`star-rating-${criterionId}`} className="flex items-center gap-2">
        {[1, 2, 3, 4, 5].map((star) => (
          <button
            key={star}
            type="button"
            onClick={() => updateCriterionStars(selectedRound.id, criterionId, star)}
            className="focus:outline-none transition-colors"
          >
            <Star
              className={`w-8 h-8 stroke-[1.5] ${
                star <= currentStars
                  ? "fill-yellow-400 text-yellow-400"
                  : "text-muted-foreground/40 hover:text-yellow-300"
              }`}
            />
          </button>
        ))}
      </div>
    );
  };

  const renderProgressBar = () => (
    <div id="progress-bar-container" className="w-full bg-card border-b border-border px-6 py-4">
      <div className="max-w-4xl mx-auto">
        <div id="progress-timeline" className="relative flex justify-between items-start">
          <div id="progress-line-bg" className="absolute top-4 left-8 right-8 h-0.5 bg-border" />
          <div
            id="progress-line-active"
            className="absolute top-4 left-8 h-0.5 bg-primary transition-all duration-500"
            style={{ width: `${Math.max(0, (currentStepIndex / (STEPS.length - 1)) * 100 - 8)}%` }}
          />
          {STEPS.map((step, index) => (
            <div key={step.id} id={`progress-step-${step.id}`} className="flex flex-col items-center relative z-10 w-28">
              <div
                id={`progress-dot-${step.id}`}
                className={`w-8 h-8 rounded-full border-2 flex items-center justify-center transition-all duration-300 ${
                  index < currentStepIndex
                    ? "bg-primary border-primary"
                    : index === currentStepIndex
                    ? "border-primary bg-card"
                    : "border-border bg-card"
                }`}
              >
                {index < currentStepIndex && <Check className="w-4 h-4 text-primary-foreground" />}
                {index === currentStepIndex && <div className="w-2 h-2 rounded-full bg-primary" />}
              </div>
              <p
                id={`progress-label-${step.id}`}
                className={`text-xs mt-2 text-center ${
                  index <= currentStepIndex ? "text-foreground font-medium" : "text-muted-foreground"
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

  const renderBasicInfo = () => (
    <motion.div
      id="basic-info-step"
      initial={{ opacity: 0, x: 50 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -50 }}
      className="flex-1 p-6 overflow-y-auto"
    >
      <div className="max-w-2xl mx-auto">
        <div id="basic-info-card" className="bg-card rounded-2xl border border-border p-8">
          <h2 id="basic-info-title" className="text-2xl font-bold mb-6">Role Basic Information</h2>

          <div className="space-y-6">
            <div id="role-title-field">
              <label htmlFor="role-title-input" className="block text-sm font-medium mb-2">
                Role Title <span className="text-destructive">*</span>
              </label>
              <input
                id="role-title-input"
                type="text"
                value={roleTitle}
                onChange={(e) => setRoleTitle(e.target.value)}
                placeholder="e.g., Senior Software Engineer"
                className="w-full px-4 py-3 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div id="level-field">
                <label htmlFor="level-select" className="block text-sm font-medium mb-2">Level</label>
                <select
                  id="level-select"
                  value={level}
                  onChange={(e) => setLevel(e.target.value)}
                  className="w-full px-4 py-3 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                >
                  <option value="">Select level</option>
                  <option value="Junior">Junior</option>
                  <option value="Mid">Mid</option>
                  <option value="Senior">Senior</option>
                  <option value="Staff">Staff</option>
                  <option value="Principal">Principal</option>
                </select>
              </div>

              <div id="location-field">
                <label htmlFor="location-input" className="block text-sm font-medium mb-2">Location</label>
                <input
                  id="location-input"
                  type="text"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  placeholder="e.g., Remote / San Francisco"
                  className="w-full px-4 py-3 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
              </div>
            </div>

            <div id="basic-info-actions" className="flex justify-end pt-4">
              <button
                id="next-btn-basic"
                onClick={handleNext}
                disabled={!roleTitle.trim()}
                className="flex items-center gap-2 px-8 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Next
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );

  const renderIntakeNotes = () => (
    <motion.div
      id="intake-notes-step"
      initial={{ opacity: 0, x: 50 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -50 }}
      className="flex-1 p-6 overflow-y-auto"
    >
      <div className="max-w-3xl mx-auto">
        <div id="intake-notes-card" className="bg-card rounded-2xl border border-border p-8">
          <h2 id="intake-notes-title" className="text-2xl font-bold mb-6">Intake Call Notes</h2>

          <div className="space-y-6">
            <div id="jd-field">
              <label htmlFor="jd-textarea" className="block text-sm font-medium mb-2">Job Description</label>
              <textarea
                id="jd-textarea"
                value={jobDescription}
                onChange={(e) => setJobDescription(e.target.value)}
                placeholder="Paste or type the full job description..."
                rows={8}
                className="w-full px-4 py-3 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none font-mono text-sm"
              />
            </div>

            <div id="must-have-field">
              <label className="block text-sm font-medium mb-2">Must Have Skills</label>
              <div className="flex gap-2 mb-2">
                <input
                  id="must-have-input"
                  type="text"
                  value={newMustHave}
                  onChange={(e) => setNewMustHave(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), handleAddMustHave())}
                  placeholder="Add a must-have skill..."
                  className="flex-1 px-4 py-2 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
                <button
                  id="add-must-have-btn"
                  type="button"
                  onClick={handleAddMustHave}
                  className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90"
                >
                  Add
                </button>
              </div>
              <div id="must-have-tags" className="flex flex-wrap gap-2">
                {mustHaveSkills.map((skill, i) => (
                  <span key={i} id={`must-have-tag-${i}`} className="flex items-center gap-1 px-3 py-1 bg-primary/10 text-primary rounded-full text-sm">
                    {skill}
                    <button onClick={() => setMustHaveSkills(mustHaveSkills.filter((_, idx) => idx !== i))} className="hover:text-destructive">
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                ))}
              </div>
            </div>

            <div id="good-to-have-field">
              <label className="block text-sm font-medium mb-2">Good to Have Skills</label>
              <div className="flex gap-2 mb-2">
                <input
                  id="good-to-have-input"
                  type="text"
                  value={newGoodToHave}
                  onChange={(e) => setNewGoodToHave(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), handleAddGoodToHave())}
                  placeholder="Add a good-to-have skill..."
                  className="flex-1 px-4 py-2 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
                <button
                  id="add-good-to-have-btn"
                  type="button"
                  onClick={handleAddGoodToHave}
                  className="px-4 py-2 bg-secondary text-secondary-foreground rounded-lg hover:bg-secondary/80"
                >
                  Add
                </button>
              </div>
              <div id="good-to-have-tags" className="flex flex-wrap gap-2">
                {goodToHaveSkills.map((skill, i) => (
                  <span key={i} id={`good-to-have-tag-${i}`} className="flex items-center gap-1 px-3 py-1 bg-secondary text-secondary-foreground rounded-full text-sm">
                    {skill}
                    <button onClick={() => setGoodToHaveSkills(goodToHaveSkills.filter((_, idx) => idx !== i))} className="hover:text-destructive">
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                ))}
              </div>
            </div>

            <div id="notes-field">
              <label htmlFor="intake-notes-textarea" className="block text-sm font-medium mb-2">Additional Notes</label>
              <textarea
                id="intake-notes-textarea"
                value={intakeNotes}
                onChange={(e) => setIntakeNotes(e.target.value)}
                placeholder="Notes from the intake call with the hiring manager..."
                rows={4}
                className="w-full px-4 py-3 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none"
              />
            </div>

            <div id="intake-actions" className="flex justify-between pt-4">
              <button
                id="back-btn-intake"
                onClick={handleBack}
                className="flex items-center gap-2 px-6 py-3 border border-border rounded-lg hover:bg-secondary transition-colors"
              >
                <ArrowLeft className="w-4 h-4" />
                Back
              </button>
              <button
                id="next-btn-intake"
                onClick={handleNext}
                className="flex items-center gap-2 px-8 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
              >
                Next
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );

  const renderInterviewPlan = () => (
    <motion.div
      id="interview-plan-step"
      initial={{ opacity: 0, x: 50 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -50 }}
      className="flex-1 flex min-h-0"
    >
      <aside id="rounds-sidebar" className="w-64 border-r border-border bg-card p-5 overflow-y-auto">
        <div id="sidebar-header" className="mb-6">
          <div id="recommended-plan-box" className="p-5 border-2 border-border rounded-xl bg-secondary/30">
            <h2 id="recommended-plan-title" className="text-lg font-bold mb-4">Recommended Plan</h2>
            <p id="role-info" className="text-lg font-semibold">{roleTitle}</p>
            {location && (
              <div id="location-info" className="flex items-center gap-2 text-base text-muted-foreground mt-2">
                <MapPin className="w-5 h-5" />
                <span>{location}</span>
              </div>
            )}
            {level && (
              <div id="experience-info" className="flex items-center gap-2 text-base text-muted-foreground mt-2">
                <Briefcase className="w-5 h-5" />
                <span>{level}</span>
              </div>
            )}
          </div>
        </div>

        <div id="rounds-timeline" className="relative pl-8 mt-6">
          <div id="timeline-vertical-line" className="absolute left-[13px] top-3 bottom-16 w-0.5 bg-border" />

          <div id="rounds-list" className="space-y-14">
            {rounds.map((round, index) => (
              <div
                key={round.id}
                id={`round-item-${round.id}`}
                className="relative cursor-pointer"
                onClick={() => setSelectedRoundIndex(index)}
              >
                <div
                  id={`timeline-dot-${round.id}`}
                  className={`absolute -left-8 top-1 w-6 h-6 rounded-full border-2 flex items-center justify-center bg-card ${
                    selectedRoundIndex === index ? "border-primary" : "border-border"
                  }`}
                >
                  {selectedRoundIndex === index && <Check className="w-3 h-3 text-primary" />}
                </div>

                <div id={`round-content-${round.id}`} className="flex items-start justify-between">
                  <div>
                    <p id={`round-label-${round.id}`} className={`text-sm ${selectedRoundIndex === index ? "text-foreground font-medium" : "text-muted-foreground"}`}>
                      Round {index + 1}
                    </p>
                    <p id={`round-name-${round.id}`} className={`text-base font-bold ${selectedRoundIndex === index ? "text-foreground" : "text-muted-foreground"}`}>
                      {round.name}
                    </p>
                  </div>
                  {rounds.length > 1 && (
                    <button
                      id={`delete-round-${round.id}`}
                      type="button"
                      className="p-1.5 text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950 rounded-lg transition-colors"
                      onClick={(e) => deleteRound(round.id, e)}
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>

          <button
            id="add-round-btn"
            onClick={addRound}
            className="mt-10 flex items-center gap-2 px-4 py-2 border border-border rounded-lg hover:bg-secondary transition-colors text-sm"
          >
            <Plus className="w-4 h-4" />
            Add Round
          </button>
        </div>
      </aside>

      <main id="builder-main" className="flex-1 bg-secondary/30 p-6 overflow-y-auto">
        {selectedRound && (
          <div id="builder-card" className="bg-card rounded-2xl border border-border p-8">
            <div id="round-header-section" className="flex items-center justify-between mb-8">
              <div className="flex items-center gap-4">
                <h1 id="round-title" className="text-2xl font-bold">
                  Round {selectedRoundIndex + 1} : {selectedRound.name}
                </h1>
                <button
                  id="view-breakdown-btn"
                  onClick={() => setShowDetailsPopup(true)}
                  className="px-4 py-2 border border-border rounded-lg hover:bg-secondary transition-colors text-sm"
                >
                  View Breakdown
                </button>
              </div>
              <span id="date-created" className="text-sm text-muted-foreground">Date Created : {new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}</span>
            </div>

            <div id="scorecard-container" className="border-2 border-border rounded-2xl p-8">
              <div id="scorecard-header" className="flex items-center justify-between mb-8">
                <h2 id="scorecard-title" className="text-2xl font-bold">Score Card Template</h2>
                <span id="round-verdict-badge" className="px-5 py-2 text-base font-bold border-2 border-foreground rounded-lg bg-background tracking-wide">
                  Verdict
                </span>
              </div>

              <div id="criteria-list" className="space-y-6">
                {selectedRound.scoreCriteria.map((criterion) => (
                  <div key={criterion.id} id={`criterion-${criterion.id}`} className="border-2 border-border rounded-xl p-6">
                    <div id={`criterion-header-${criterion.id}`} className="flex items-start justify-between mb-4">
                      {editingCriterionId === criterion.id ? (
                        <div className="flex-1 pr-4 flex items-center gap-2">
                          <input
                            id={`edit-input-${criterion.id}`}
                            value={criterion.description}
                            onChange={(e) => updateCriterionDescription(selectedRound.id, criterion.id, e.target.value)}
                            className="flex-1 px-3 py-2 text-lg font-medium border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                            autoFocus
                          />
                          <button
                            id={`save-criterion-${criterion.id}`}
                            className="p-2 text-primary hover:bg-primary/10 rounded-lg transition-colors"
                            onClick={() => setEditingCriterionId(null)}
                          >
                            <Check className="w-5 h-5" />
                          </button>
                        </div>
                      ) : (
                        <>
                          <p id={`criterion-desc-${criterion.id}`} className="font-medium text-lg flex-1 pr-4">{criterion.description}</p>
                          <div className="flex items-center gap-2">
                            <button
                              id={`edit-criterion-${criterion.id}`}
                              className="p-2 text-muted-foreground hover:text-foreground hover:bg-secondary rounded-lg transition-colors"
                              onClick={() => setEditingCriterionId(criterion.id)}
                            >
                              <Pencil className="w-5 h-5" />
                            </button>
                            <button
                              id={`guidelines-btn-${criterion.id}`}
                              className="px-3 py-1.5 border border-border rounded-lg hover:bg-secondary transition-colors text-sm"
                              onClick={() => setShowGuidelinesPopup(true)}
                            >
                              guidelines
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                    <textarea
                      id={`feedback-${criterion.id}`}
                      placeholder="Add feedback..."
                      value={criterion.feedback || ""}
                      onChange={(e) => updateCriterionFeedback(selectedRound.id, criterion.id, e.target.value)}
                      className="w-full min-h-[80px] p-3 border-2 border-border rounded-lg bg-background text-sm resize-none focus:outline-none focus:border-primary mb-4"
                    />
                    <div id={`criterion-rating-${criterion.id}`} className="flex items-center justify-between">
                      {renderStarRating(criterion.id, criterion.stars)}
                      <button
                        id={`remove-criterion-${criterion.id}`}
                        className="p-2 text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950 rounded-lg transition-colors"
                        onClick={() => removeCriterion(selectedRound.id, criterion.id)}
                      >
                        <Trash2 className="w-5 h-5" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>

              <button
                id="add-more-btn"
                onClick={() => addCriterion(selectedRound.id)}
                className="mt-6 flex items-center gap-2 px-4 py-2 border border-border rounded-lg hover:bg-secondary transition-colors text-sm"
              >
                <Plus className="w-4 h-4" />
                Add More
              </button>
            </div>

            <div id="builder-actions" className="flex justify-end mt-8">
              <button
                id="next-round-btn"
                onClick={handleNext}
                className="px-12 py-3 bg-primary text-primary-foreground rounded-xl hover:bg-primary/90 transition-colors text-base"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </main>

      {showDetailsPopup && selectedRound && (
        <div
          id="popup-overlay"
          className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
          onClick={() => setShowDetailsPopup(false)}
        >
          <div
            id="details-popup"
            className="w-full max-w-2xl max-h-[85vh] bg-card border border-border rounded-2xl shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6 border-b border-border flex items-center justify-between">
              <div className="flex items-center gap-3 flex-1">
                <span className="font-bold text-xl">Round Details -</span>
                <input
                  id="round-name-input"
                  value={selectedRound.name}
                  onChange={(e) => updateRoundName(selectedRound.id, e.target.value)}
                  className="font-bold text-xl h-10 w-48 px-2 border border-dashed border-border rounded-lg bg-background focus:outline-none focus:border-primary"
                />
              </div>
              <button
                id="close-popup-btn"
                className="p-2 hover:bg-secondary rounded-lg"
                onClick={() => setShowDetailsPopup(false)}
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-6 overflow-y-auto max-h-[calc(85vh-80px)] space-y-8">
              <div id="description-section">
                <h4 className="text-sm font-bold mb-3">Description</h4>
                <textarea
                  id="description-textarea"
                  value={selectedRound.description}
                  onChange={(e) => updateRoundDescription(selectedRound.id, e.target.value)}
                  className="w-full min-h-[120px] p-3 text-sm text-muted-foreground leading-relaxed border border-border rounded-lg bg-background resize-none focus:outline-none focus:border-primary"
                />
              </div>

              <div id="skills-section">
                <h4 className="text-sm font-bold mb-3">Skills tested :</h4>
                <div className="flex flex-wrap gap-2 mb-3">
                  {selectedRound.skills.map((skill, idx) => (
                    <span
                      key={idx}
                      id={`skill-tag-${idx}`}
                      className="px-3 py-1.5 text-sm border border-border rounded-lg bg-background flex items-center gap-2"
                    >
                      {skill}
                      <button
                        type="button"
                        onClick={() => removeSkill(selectedRound.id, idx)}
                        className="text-red-500 hover:text-red-600"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </span>
                  ))}
                </div>
                <div className="flex gap-2">
                  <input
                    id="add-skill-input"
                    placeholder="Add a skill..."
                    value={newSkill}
                    onChange={(e) => setNewSkill(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && addSkill(selectedRound.id)}
                    className="h-10 flex-1 px-3 border border-border rounded-lg bg-background focus:outline-none focus:border-primary"
                  />
                  <button
                    id="add-skill-btn"
                    className="h-10 px-4 flex items-center gap-2 border border-border rounded-lg hover:bg-secondary transition-colors"
                    onClick={() => addSkill(selectedRound.id)}
                  >
                    <Plus className="w-4 h-4" />
                    Add
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {showGuidelinesPopup && selectedRound && (
        <div
          id="guidelines-overlay"
          className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
          onClick={() => setShowGuidelinesPopup(false)}
        >
          <div
            id="guidelines-popup"
            className="w-full max-w-3xl max-h-[90vh] bg-card border border-border rounded-2xl shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6 border-b border-border flex items-center justify-between">
              <h3 className="font-bold text-xl">{selectedRound.name} Guidelines</h3>
              <button
                id="close-guidelines-btn"
                className="p-2 hover:bg-secondary rounded-lg"
                onClick={() => setShowGuidelinesPopup(false)}
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-6 overflow-y-auto max-h-[calc(90vh-80px)] space-y-4">
              {selectedRound.guidelines.map((guideline, index) => (
                <div key={guideline.id} id={`guideline-${guideline.id}`} className="border border-border rounded-xl p-4 space-y-3">
                  <div className="flex items-start gap-3">
                    <span className="w-6 h-6 rounded-full bg-primary text-primary-foreground flex items-center justify-center text-sm flex-shrink-0 mt-1">
                      {index + 1}
                    </span>
                    <div className="flex-1 space-y-2">
                      <input
                        id={`guideline-title-${guideline.id}`}
                        value={guideline.title}
                        onChange={(e) => updateGuideline(selectedRound.id, guideline.id, "title", e.target.value)}
                        className="w-full font-semibold text-base h-9 px-2 border border-dashed border-border rounded-lg bg-background focus:outline-none focus:border-primary"
                        placeholder="Guideline title"
                      />
                      <textarea
                        id={`guideline-desc-${guideline.id}`}
                        value={guideline.description}
                        onChange={(e) => updateGuideline(selectedRound.id, guideline.id, "description", e.target.value)}
                        className="w-full min-h-[60px] p-2 text-sm text-muted-foreground border border-border rounded-lg bg-background resize-none focus:outline-none focus:border-primary"
                        placeholder="Guideline description"
                      />
                    </div>
                    <button
                      type="button"
                      className="p-1.5 text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950 rounded-lg transition-colors"
                      onClick={() => removeGuideline(selectedRound.id, guideline.id)}
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ))}

              <div id="add-guideline-section" className="border-2 border-dashed border-border rounded-xl p-4 space-y-3">
                <p className="text-sm font-medium text-muted-foreground">Add New Guideline</p>
                <input
                  id="new-guideline-title"
                  value={newGuidelineTitle}
                  onChange={(e) => setNewGuidelineTitle(e.target.value)}
                  placeholder="Guideline title"
                  className="w-full h-9 px-3 border border-border rounded-lg bg-background focus:outline-none focus:border-primary"
                />
                <textarea
                  id="new-guideline-desc"
                  value={newGuidelineDesc}
                  onChange={(e) => setNewGuidelineDesc(e.target.value)}
                  placeholder="Guideline description (optional)"
                  className="w-full min-h-[60px] p-2 text-sm border border-border rounded-lg bg-background resize-none focus:outline-none focus:border-primary"
                />
                <button
                  id="add-guideline-btn"
                  className="flex items-center gap-2 px-4 py-2 border border-border rounded-lg hover:bg-secondary transition-colors"
                  onClick={() => addGuideline(selectedRound.id)}
                >
                  <Plus className="w-4 h-4" />
                  Add Guideline
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </motion.div>
  );

  const renderConfirmation = () => (
    <motion.div
      id="confirmation-step"
      initial={{ opacity: 0, x: 50 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -50 }}
      className="flex-1 p-6 overflow-y-auto"
    >
      <div className="max-w-5xl mx-auto">
        <div id="confirm-plan-card" className="bg-card rounded-2xl border border-border p-8">
          <h2 id="confirm-plan-title" className="text-2xl font-bold mb-8">Confirm Plan</h2>

          <div id="rounds-timeline" className="relative mb-12 pt-6">
            <div id="timeline-line" className="absolute top-9 left-8 right-8 h-0.5 bg-border" />
            <div id="timeline-rounds" className="flex justify-between relative px-4">
              {rounds.map((round, index) => (
                <div key={round.id} id={`timeline-round-${round.id}`} className="flex flex-col items-center w-32">
                  <div
                    id={`timeline-dot-${index}`}
                    className="w-7 h-7 rounded-full bg-primary border-2 border-primary flex items-center justify-center z-10"
                  >
                    <Check className="w-4 h-4 text-primary-foreground" />
                  </div>
                  <p id={`round-label-${index}`} className="text-sm font-medium mt-4 text-center leading-tight">
                    Round {index + 1}
                  </p>
                  <p id={`round-name-${index}`} className="text-sm text-muted-foreground text-center">
                    {round.name}
                  </p>
                  <button
                    id={`expand-btn-${round.id}`}
                    className="mt-3 px-3 py-1 border border-border rounded-lg text-xs hover:bg-secondary transition-colors"
                    onClick={() => setExpandedRound(expandedRound === round.id ? null : round.id)}
                  >
                    {expandedRound === round.id ? "Collapse" : "Expand"}
                  </button>
                </div>
              ))}
            </div>
          </div>

          {expandedRound && (
            <div id="expanded-scorecard" className="mb-8 p-6 bg-secondary/30 rounded-xl">
              <h3 id="expanded-title" className="text-lg font-semibold mb-4">
                {rounds.find(r => r.id === expandedRound)?.name} - Score Card
              </h3>
              <div id="expanded-criteria" className="space-y-3">
                {rounds.find(r => r.id === expandedRound)?.scoreCriteria.map((criterion) => (
                  <div key={criterion.id} id={`expanded-criterion-${criterion.id}`} className="flex items-center justify-between p-3 bg-card rounded-lg">
                    <p className="text-sm flex-1">{criterion.description}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div id="confirmation-actions" className="flex justify-center gap-4">
            <button
              id="go-back-btn"
              onClick={handleBack}
              className="px-8 py-3 border border-border rounded-xl hover:bg-secondary transition-colors"
            >
              Go Back and Edit
            </button>
            <button
              id="confirm-save-btn"
              onClick={handleSave}
              className="px-8 py-3 bg-primary text-primary-foreground rounded-xl hover:bg-primary/90 transition-colors"
            >
              Confirm and Save Plan
            </button>
          </div>
        </div>
      </div>
    </motion.div>
  );

  const renderStepContent = () => {
    switch (currentStep) {
      case "basic-info":
        return renderBasicInfo();
      case "intake-notes":
        return renderIntakeNotes();
      case "interview-plan":
        return renderInterviewPlan();
      case "confirmation":
        return renderConfirmation();
      default:
        return null;
    }
  };

  if (!customer) {
    return (
      <div className="min-h-screen bg-secondary/30 flex items-center justify-center">
        <div className="text-center">
          <p className="text-muted-foreground mb-4">Customer not found</p>
          <Link href="/customers" className="text-primary hover:underline">Back to customers</Link>
        </div>
      </div>
    );
  }

  return (
    <AuthGuard>
    <div id="new-requisition-page" className="h-screen flex flex-col">
      <nav id="admin-nav" className="bg-card border-b border-border">
        <div className="px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link href="/" className="flex items-center gap-3">
              <Building2 className="w-8 h-8 text-primary" />
              <span className="text-xl font-bold">OpenRecruiting Admin</span>
            </Link>
          </div>
          <div className="flex items-center gap-4">
            <Link
              href={`/customers/${customerId}`}
              id="back-to-customer"
              className="flex items-center gap-2 px-4 py-2 rounded-lg hover:bg-secondary transition-colors text-sm"
            >
              <ArrowLeft className="w-4 h-4" />
              Back to {customer.company}
            </Link>
            <ThemeToggle />
            <button
              id="logout-btn"
              onClick={handleLogout}
              className="flex items-center gap-2 px-4 py-2 text-destructive hover:bg-destructive/10 rounded-lg transition-colors"
            >
              <LogOut className="w-4 h-4" />
              Logout
            </button>
          </div>
        </div>
      </nav>

      {renderProgressBar()}

      <div id="step-content" className="flex-1 flex flex-col bg-secondary/30 min-h-0">
        <AnimatePresence mode="wait">
          {renderStepContent()}
        </AnimatePresence>
      </div>
    </div>
    </AuthGuard>
  );
}
