"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  Building2,
  ArrowLeft,
  ChevronRight,
  MapPin,
  Briefcase,
  LogOut,
  Loader2,
  FileText,
  Check,
  AlertCircle,
  ClipboardList,
  Plus,
  SkipForward,
  RefreshCw,
  Clock,
  Sparkles,
} from "lucide-react";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { AuthGuard } from "@/components/auth-guard";
import { createClient } from "@/lib/supabase/client";

interface Requisition {
  id: string;
  organization_id: string;
  role_title: string;
  role_location: string | null;
  experience_min_years: number;
  experience_max_years: number | null;
  experience_display: string;
  status: string;
  intake_transcript: string | null;
  intake_processing_status: string | null;
  intake_processing_error: string | null;
}

interface Organization {
  id: string;
  name: string;
}

interface PlanRound {
  id: string;
  round_number: number;
  name: string;
  category: string | null;
  duration_minutes: number;
  duration_display: string;
  description: string | null;
  skills: string[];
  feedback_questions: Array<{
    id: string;
    heading: string;
    description: string | null;
    question_number: number;
  }>;
}

interface Plan {
  requisition_id: string;
  total_rounds: number;
  total_duration_minutes: number;
  total_duration_display: string;
  rounds: PlanRound[];
}

interface AssessmentTemplate {
  id: string;
  title: string;
  description: string | null;
  role_seniority: string | null;
  tools_enabled: string[];
  time_limit_minutes: number;
  status: string;
}

type IntakeState = "idle" | "processing" | "completed" | "failed";

export default function PlanInputPage() {
  const params = useParams();
  const router = useRouter();
  const reqId = params.id as string;

  const [requisition, setRequisition] = useState<Requisition | null>(null);
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [intakeState, setIntakeState] = useState<IntakeState>("idle");
  const [transcript, setTranscript] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [processingError, setProcessingError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [step, setStep] = useState<"interview" | "assessment">("interview");
  const [assessmentTemplates, setAssessmentTemplates] = useState<AssessmentTemplate[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
  const [showNewAssessment, setShowNewAssessment] = useState(false);
  const [taskDefinitionJson, setTaskDefinitionJson] = useState("");
  const [evalRubricJson, setEvalRubricJson] = useState("");
  const [taskJsonError, setTaskJsonError] = useState<string | null>(null);
  const [evalJsonError, setEvalJsonError] = useState<string | null>(null);
  const [toolsEnabled, setToolsEnabled] = useState<string[]>(["excalidraw"]);
  const [assessmentError, setAssessmentError] = useState<string | null>(null);
  const [creatingAssessment, setCreatingAssessment] = useState(false);

  const inferFromJson = (taskJson: string, evalJson: string) => {
    const defaults = {
      title: "",
      description: "",
      duration: 60,
      role_seniority: "",
    };
    try {
      const task = JSON.parse(taskJson);
      defaults.title = task?.scenario?.title || task?.display?.title || "";
      defaults.description = task?.scenario?.challenge_statement || task?.task_requirements?.primary_objective || task?.display?.description || "";
      defaults.role_seniority = task?.task_metadata?.seniority_level || task?.display?.role_seniority || "";
      defaults.duration = task?.task_metadata?.estimated_time || task?.metadata?.estimated_time_minutes || 60;
    } catch {
      // ignore
    }
    try {
      const evalData = JSON.parse(evalJson);
      if (!defaults.title && evalData?.rubric_metadata?.task_title) {
        defaults.title = evalData.rubric_metadata.task_title;
      }
      if (!defaults.role_seniority && evalData?.rubric_metadata?.role_seniority) {
        defaults.role_seniority = evalData.rubric_metadata.role_seniority;
      }
    } catch {
      // ignore
    }
    return defaults;
  };

  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  // V2 backend base — admin endpoints ported to /api/v2/admin.

  const API_V2_URL = process.env.NEXT_PUBLIC_API_V2_URL || "http://localhost:8004";

  const getHeaders = async () => {
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) {
      router.push("/login");
      return null;
    }
    return {
      "Authorization": `Bearer ${session.access_token}`,
      "Content-Type": "application/json",
    };
  };

  useEffect(() => {
    fetchData();
    return () => stopPolling();
  }, [reqId]);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const startPolling = useCallback(() => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      const headers = await getHeaders();
      if (!headers) return;

      try {
        const statusResp = await fetch(`${API_V2_URL}/api/v2/admin/intake-jobs/${reqId}/status`, { headers });
        if (!statusResp.ok) return;
        const statusData = await statusResp.json();

        if (statusData.intake_processing_status === "completed") {
          stopPolling();
          router.push(`/requisitions/${reqId}/plan/edit`);
          return;
        } else if (statusData.intake_processing_status === "failed") {
          stopPolling();
          setIntakeState("failed");
          setProcessingError(statusData.intake_processing_error || "Processing failed");
        }
      } catch {
        // silently retry on next interval
      }
    }, 3000);
  }, [reqId, API_URL]);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);

      const headers = await getHeaders();
      if (!headers) return;

      const reqResponse = await fetch(`${API_V2_URL}/api/v2/admin/requisitions/${reqId}`, { headers });
      if (!reqResponse.ok) throw new Error("Failed to fetch requisition");
      const reqData = await reqResponse.json();
      setRequisition(reqData);

      if (reqData.intake_transcript) {
        setTranscript(reqData.intake_transcript);
      }

      const planResponse = await fetch(`${API_V2_URL}/api/v2/admin/requisitions/${reqId}/plan`, { headers });
      let hasPlan = false;
      if (planResponse.ok) {
        const planData = await planResponse.json();
        if (planData.rounds && planData.rounds.length > 0) {
          setPlan(planData);
          hasPlan = true;
        }
      }

      if (reqData.intake_processing_status === "processing") {
        setIntakeState("processing");
        startPolling();
      } else if (hasPlan) {
        router.push(`/requisitions/${reqId}/plan/edit`);
        return;
      } else if (reqData.intake_processing_status === "failed") {
        setIntakeState("failed");
        setProcessingError(reqData.intake_processing_error || "Processing failed");
      } else {
        setIntakeState("idle");
      }

      const orgResponse = await fetch(`${API_V2_URL}/api/v2/admin/organizations/${reqData.organization_id}`, { headers });
      if (orgResponse.ok) {
        const orgData = await orgResponse.json();
        setOrganization(orgData);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch data");
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem("admin_auth");
    router.push("/login");
  };

  const handleGeneratePlan = async () => {
    if (!transcript.trim() || isSubmitting) return;

    try {
      setIsSubmitting(true);
      setError(null);
      setProcessingError(null);

      const headers = await getHeaders();
      if (!headers) return;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/intake-jobs`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          requisition_id: reqId,
          intake_transcript: transcript,
        }),
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || "Failed to trigger plan generation");
      }

      const result = await response.json();
      if (result.status === "rejected") {
        if (result.reason === "Already processing") {
          setIntakeState("processing");
          setPlan(null);
          startPolling();
          return;
        }
        throw new Error(result.reason || "Request rejected");
      }

      setIntakeState("processing");
      setPlan(null);
      startPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate plan");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRegenerate = () => {
    setIntakeState("idle");
    setPlan(null);
    setProcessingError(null);
  };

  const handleProceedToAssessment = () => {
    setStep("assessment");
    fetchAssessmentTemplates();
  };

  const handleGoToEdit = () => {
    router.push(`/requisitions/${reqId}/plan/edit`);
  };

  const fetchAssessmentTemplates = useCallback(async () => {
    try {
      setLoadingTemplates(true);
      const headers = await getHeaders();
      if (!headers) return;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/assessment-templates?status=published`, { headers });
      if (response.ok) {
        const data = await response.json();
        setAssessmentTemplates(data.templates || []);
      }
    } catch (err) {
      console.warn("Failed to fetch assessment templates:", err);
      setAssessmentTemplates([]);
    } finally {
      setLoadingTemplates(false);
    }
  }, [API_URL]);

  const validateAssessmentJson = (jsonString: string, type: "task" | "eval"): boolean => {
    if (!jsonString.trim()) {
      if (type === "task") setTaskJsonError("Task definition JSON is required");
      else setEvalJsonError("Evaluation rubric JSON is required");
      return false;
    }
    try {
      JSON.parse(jsonString);
      if (type === "task") setTaskJsonError(null);
      else setEvalJsonError(null);
      return true;
    } catch {
      if (type === "task") setTaskJsonError("Invalid JSON format");
      else setEvalJsonError("Invalid JSON format");
      return false;
    }
  };

  const toggleTool = (tool: string) => {
    setToolsEnabled(prev =>
      prev.includes(tool) ? prev.filter(t => t !== tool) : [...prev, tool]
    );
  };

  const handleSkipAssessment = () => {
    router.push(`/requisitions/${reqId}/plan/edit`);
  };

  const handleAddAssessmentFromLibrary = async () => {
    if (!selectedTemplateId) return;

    try {
      setCreatingAssessment(true);
      setAssessmentError(null);
      const headers = await getHeaders();
      if (!headers) return;

      const template = assessmentTemplates.find(t => t.id === selectedTemplateId);
      if (!template) return;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/requisitions/${reqId}/rounds`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          name: template.title,
          category: "assessment",
          duration_minutes: template.time_limit_minutes,
          description: template.description || "Assessment round",
          skills: [],
          round_type: "assessment",
          assessment_template_id: template.id,
          round_number: 1,
        }),
      });

      if (!response.ok) throw new Error("Failed to add assessment round");
      router.push(`/requisitions/${reqId}/plan/edit`);
    } catch (err) {
      setAssessmentError(err instanceof Error ? err.message : "Failed to add assessment");
    } finally {
      setCreatingAssessment(false);
    }
  };

  const handleCreateNewAssessment = async () => {
    const taskValid = validateAssessmentJson(taskDefinitionJson, "task");
    const evalValid = validateAssessmentJson(evalRubricJson, "eval");
    if (!taskValid || !evalValid) return;

    const inferred = inferFromJson(taskDefinitionJson, evalRubricJson);
    if (!inferred.title.trim()) {
      setAssessmentError("Could not infer title from JSON. Ensure scenario.title exists in task JSON.");
      return;
    }

    try {
      setCreatingAssessment(true);
      setAssessmentError(null);
      const headers = await getHeaders();
      if (!headers) return;

      const templateResponse = await fetch(`${API_V2_URL}/api/v2/admin/assessment-templates`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          title: inferred.title,
          description: inferred.description || null,
          role_seniority: inferred.role_seniority || null,
          time_limit_minutes: inferred.duration,
          tools_enabled: toolsEnabled,
          task_definition: JSON.parse(taskDefinitionJson),
          evaluation_rubric: JSON.parse(evalRubricJson),
          status: "published",
        }),
      });

      if (!templateResponse.ok) {
        const errData = await templateResponse.json();
        throw new Error(errData.detail || "Failed to create assessment template");
      }

      const newTemplate = await templateResponse.json();

      const roundResponse = await fetch(`${API_V2_URL}/api/v2/admin/requisitions/${reqId}/rounds`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          name: inferred.title,
          category: "assessment",
          duration_minutes: inferred.duration,
          description: inferred.description || "Assessment round",
          skills: [],
          round_type: "assessment",
          assessment_template_id: newTemplate.id,
          round_number: 1,
        }),
      });

      if (!roundResponse.ok) throw new Error("Failed to add assessment round");
      router.push(`/requisitions/${reqId}/plan/edit`);
    } catch (err) {
      setAssessmentError(err instanceof Error ? err.message : "Failed to create assessment");
    } finally {
      setCreatingAssessment(false);
    }
  };

  if (loading) {
    return (
      <div id="plan-loading" className="min-h-screen bg-secondary/30 flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    );
  }

  if (error && !requisition) {
    return (
      <div id="plan-error" className="min-h-screen bg-secondary/30 flex items-center justify-center">
        <div className="text-center">
          <p className="text-destructive mb-4">{error || "Requisition not found"}</p>
          <Link href="/customers" className="text-primary hover:underline">
            Back to customers
          </Link>
        </div>
      </div>
    );
  }

  if (!requisition) return null;

  const categoryColors: Record<string, string> = {
    coding: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
    design: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
    behavioral: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
    domain: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400",
    culture: "bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-400",
    assessment: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
  };

  const renderInterviewStep = () => {
    if (intakeState === "processing") {
      return (
        <div id="plan-processing-card" className="bg-card rounded-2xl border border-border p-8">
          <div className="flex flex-col items-center text-center py-12">
            <div className="relative mb-6">
              <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center">
                <Sparkles className="w-8 h-8 text-primary animate-pulse" />
              </div>
            </div>
            <h2 id="plan-processing-title" className="text-xl font-semibold mb-2">Generating Interview Plan</h2>
            <p id="plan-processing-desc" className="text-muted-foreground mb-6 max-w-md">
              Analyzing your intake transcript and role context to create a tailored interview scorecard. This typically takes 30-60 seconds.
            </p>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="w-4 h-4 animate-spin" />
              Processing...
            </div>
          </div>
        </div>
      );
    }

    if (intakeState === "completed" && plan) {
      return (
        <div id="plan-completed-card" className="space-y-6">
          <div className="bg-card rounded-2xl border border-border p-8">
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <div className="w-12 h-12 rounded-full bg-green-100 dark:bg-green-900/30 flex items-center justify-center">
                  <Check className="w-6 h-6 text-green-600 dark:text-green-400" />
                </div>
                <div>
                  <h2 id="plan-completed-title" className="text-xl font-semibold">Interview Plan Generated</h2>
                  <p className="text-muted-foreground text-sm">
                    {plan.total_rounds} rounds, {plan.total_duration_display} total
                  </p>
                </div>
              </div>
              <button
                id="regenerate-plan-btn"
                onClick={handleRegenerate}
                className="flex items-center gap-2 px-4 py-2 border border-border rounded-lg hover:bg-secondary transition-colors text-sm"
              >
                <RefreshCw className="w-4 h-4" />
                Regenerate
              </button>
            </div>

            <div className="space-y-4">
              {plan.rounds.map((round) => (
                <div
                  key={round.id}
                  id={`plan-round-card-${round.round_number}`}
                  className="border border-border rounded-xl p-5"
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-bold text-muted-foreground">
                        {round.round_number}
                      </span>
                      <h3 className="font-semibold">{round.name}</h3>
                      {round.category && (
                        <span className={`text-xs px-2 py-0.5 rounded-full ${categoryColors[round.category] || "bg-secondary text-foreground"}`}>
                          {round.category}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1 text-sm text-muted-foreground">
                      <Clock className="w-3.5 h-3.5" />
                      {round.duration_display}
                    </div>
                  </div>

                  {round.description && (
                    <p className="text-sm text-muted-foreground mb-3">{round.description}</p>
                  )}

                  {round.skills.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mb-3">
                      {round.skills.map((skill, i) => (
                        <span
                          key={i}
                          id={`plan-round-${round.round_number}-skill-${i}`}
                          className="text-xs px-2 py-0.5 bg-secondary rounded-md"
                        >
                          {skill}
                        </span>
                      ))}
                    </div>
                  )}

                  {round.feedback_questions.length > 0 && (
                    <div className="border-t border-border pt-3 mt-3">
                      <p className="text-xs font-medium text-muted-foreground mb-2">
                        Evaluation Questions ({round.feedback_questions.length})
                      </p>
                      <div className="space-y-1.5">
                        {round.feedback_questions.map((q) => (
                          <div key={q.id} id={`plan-round-${round.round_number}-q-${q.question_number}`} className="text-sm">
                            <span className="font-medium">{q.heading}</span>
                            {q.description && (
                              <span className="text-muted-foreground ml-1">— {q.description}</span>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div id="plan-completed-actions" className="flex justify-between">
            <Link
              href={`/requisitions/${reqId}/intake`}
              id="plan-back-to-intake-btn"
              className="flex items-center gap-2 px-6 py-3 border border-border rounded-lg hover:bg-secondary transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              Back to Intake
            </Link>
            <div className="flex gap-3">
              <button
                id="plan-go-to-edit-btn"
                onClick={handleGoToEdit}
                className="flex items-center gap-2 px-6 py-3 border border-border rounded-lg hover:bg-secondary transition-colors"
              >
                Edit Plan
                <ChevronRight className="w-4 h-4" />
              </button>
              <button
                id="plan-proceed-assessment-btn"
                onClick={handleProceedToAssessment}
                className="flex items-center gap-2 px-8 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
              >
                Next: Assessment Step
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      );
    }

    if (intakeState === "failed") {
      return (
        <div id="plan-failed-card" className="bg-card rounded-2xl border border-border p-8">
          <div className="flex flex-col items-center text-center py-8">
            <div className="w-12 h-12 rounded-full bg-destructive/10 flex items-center justify-center mb-4">
              <AlertCircle className="w-6 h-6 text-destructive" />
            </div>
            <h2 id="plan-failed-title" className="text-xl font-semibold mb-2">Plan Generation Failed</h2>
            <p className="text-muted-foreground mb-2 max-w-md">
              Something went wrong while generating your interview plan.
            </p>
            {processingError && (
              <p id="plan-failed-error" className="text-sm text-destructive mb-6 max-w-md">
                {processingError}
              </p>
            )}
            <button
              id="plan-retry-btn"
              onClick={handleRegenerate}
              className="flex items-center gap-2 px-6 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
              Try Again
            </button>
          </div>
        </div>
      );
    }

    // idle state
    return (
      <div id="plan-transcript-card" className="bg-card rounded-2xl border border-border p-8">
        <div className="flex items-center gap-3 mb-6">
          <FileText className="w-6 h-6 text-primary" />
          <h2 id="plan-transcript-title" className="text-xl font-semibold">Generate Interview Plan</h2>
        </div>

        <textarea
          id="plan-transcript-input"
          value={transcript}
          onChange={(e) => setTranscript(e.target.value)}
          placeholder="Paste your intake transcript or notes here..."
          rows={10}
          className="w-full px-4 py-3 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none text-sm"
        />

        {error && (
          <div id="plan-transcript-error" className="flex items-start gap-2 text-destructive text-sm mt-3">
            <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div id="plan-transcript-actions" className="flex justify-between mt-6">
          <Link
            href={`/requisitions/${reqId}/intake`}
            id="plan-idle-back-to-intake-btn"
            className="flex items-center gap-2 px-6 py-3 border border-border rounded-lg hover:bg-secondary transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Intake
          </Link>
          <button
            id="generate-plan-btn"
            onClick={handleGeneratePlan}
            disabled={!transcript.trim() || isSubmitting}
            className="flex items-center gap-2 px-8 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            {isSubmitting ? "Submitting..." : "Generate Plan"}
          </button>
        </div>
      </div>
    );
  };

  return (
    <AuthGuard>
      <div id="plan-input-page" className="min-h-screen bg-secondary/30">
        <nav id="plan-nav" className="bg-card border-b border-border">
          <div className="px-6 py-4 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Link href="/" className="flex items-center gap-3">
                <Building2 className="w-8 h-8 text-primary" />
                <span className="text-xl font-bold">OpenRecruiting Admin</span>
              </Link>
            </div>
            <div className="flex items-center gap-4">
              {organization && (
                <Link
                  href={`/customers/${requisition.organization_id}`}
                  id="back-to-org-link"
                  className="flex items-center gap-2 px-4 py-2 rounded-lg hover:bg-secondary transition-colors text-sm"
                >
                  <ArrowLeft className="w-4 h-4" />
                  Back to {organization.name}
                </Link>
              )}
              <ThemeToggle />
              <button
                id="plan-logout-btn"
                onClick={handleLogout}
                className="flex items-center gap-2 px-4 py-2 text-destructive hover:bg-destructive/10 rounded-lg transition-colors"
              >
                <LogOut className="w-4 h-4" />
                Logout
              </button>
            </div>
          </div>
        </nav>

        <div id="plan-progress" className="w-full bg-card border-b border-border px-6 py-4">
          <div className="max-w-5xl mx-auto">
            <div id="plan-progress-bar" className="relative flex justify-between items-start">
              <div id="plan-progress-line-bg" className="absolute top-4 left-8 right-8 h-0.5 bg-border" />
              <div
                id="plan-progress-line-active"
                className="absolute top-4 left-8 h-0.5 bg-primary transition-all duration-500"
                style={{ width: step === "interview" ? "40%" : "75%" }}
              />
              {[
                { id: "basic", label: "Basic Info", complete: true },
                { id: "intake", label: "Intake Notes", complete: true },
                { id: "plan", label: "Interview Plan", complete: step === "assessment", active: step === "interview" },
                { id: "assessment", label: "Assessment (Optional)", active: step === "assessment" },
              ].map((s) => (
                <div key={s.id} id={`plan-step-${s.id}`} className="flex flex-col items-center relative z-10 w-28">
                  <div
                    id={`plan-dot-${s.id}`}
                    className={`w-8 h-8 rounded-full border-2 flex items-center justify-center transition-all duration-300 ${
                      s.complete
                        ? "bg-primary border-primary"
                        : s.active
                        ? "border-primary bg-card"
                        : "border-border bg-card"
                    }`}
                  >
                    {s.complete && (
                      <svg className="w-4 h-4 text-primary-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                    {s.active && <div className="w-2 h-2 rounded-full bg-primary" />}
                  </div>
                  <p
                    id={`plan-label-${s.id}`}
                    className={`text-xs mt-2 text-center ${
                      s.complete || s.active ? "text-foreground font-medium" : "text-muted-foreground"
                    }`}
                  >
                    {s.label}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>

        <main id="plan-main" className="max-w-4xl mx-auto p-6">
          <div id="plan-header" className="mb-6">
            <h1 id="plan-title" className="text-2xl font-bold mb-2">
              Interview Plan: {requisition.role_title}
            </h1>
            <div className="flex items-center gap-4 text-muted-foreground">
              {requisition.role_location && (
                <span id="plan-location" className="flex items-center gap-1">
                  <MapPin className="w-4 h-4" />
                  {requisition.role_location}
                </span>
              )}
              <span id="plan-experience" className="flex items-center gap-1">
                <Briefcase className="w-4 h-4" />
                {requisition.experience_display}
              </span>
            </div>
          </div>

          {step === "interview" ? (
            renderInterviewStep()
          ) : (
            <div id="assessment-step" className="bg-card rounded-2xl border border-border p-8">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-12 h-12 rounded-xl bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
                  <ClipboardList className="w-6 h-6 text-amber-600 dark:text-amber-400" />
                </div>
                <div>
                  <h2 id="assessment-step-title" className="text-xl font-semibold">Add Assessment Round (Optional)</h2>
                  <p className="text-muted-foreground text-sm">
                    Add a task-based assessment with workspace tools and automated evaluation
                  </p>
                </div>
              </div>

              <div className="p-4 bg-green-50 dark:bg-green-900/20 rounded-lg border border-green-200 dark:border-green-800 mb-6">
                <div className="flex items-center gap-2 text-green-700 dark:text-green-400">
                  <Check className="w-5 h-5" />
                  <span className="font-medium">Interview plan created successfully!</span>
                </div>
              </div>

              {!showNewAssessment ? (
                <div id="assessment-options" className="space-y-6">
                  <div id="assessment-library" className="border-2 border-border rounded-xl p-6">
                    <h3 className="font-semibold mb-4">Select from Library</h3>
                    {loadingTemplates ? (
                      <div className="flex items-center justify-center py-8">
                        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
                      </div>
                    ) : assessmentTemplates.length === 0 ? (
                      <div className="text-center py-6 text-muted-foreground">
                        <ClipboardList className="w-10 h-10 mx-auto mb-2 opacity-50" />
                        <p className="text-sm">No published assessment templates found</p>
                      </div>
                    ) : (
                      <div className="space-y-2 max-h-48 overflow-y-auto">
                        {assessmentTemplates.map((template) => (
                          <button
                            key={template.id}
                            id={`assessment-template-${template.id}`}
                            onClick={() => setSelectedTemplateId(template.id)}
                            className={`w-full p-3 border rounded-lg text-left transition-all ${
                              selectedTemplateId === template.id
                                ? "border-primary bg-primary/5"
                                : "border-border hover:border-primary/50"
                            }`}
                          >
                            <div className="flex items-center justify-between">
                              <div>
                                <h5 className="font-medium text-sm">{template.title}</h5>
                                <p className="text-xs text-muted-foreground">
                                  {template.time_limit_minutes} mins
                                  {template.role_seniority && ` • ${template.role_seniority}`}
                                </p>
                              </div>
                              {selectedTemplateId === template.id && (
                                <Check className="w-4 h-4 text-primary" />
                              )}
                            </div>
                          </button>
                        ))}
                      </div>
                    )}

                    {selectedTemplateId && (
                      <button
                        id="add-assessment-from-library-btn"
                        onClick={handleAddAssessmentFromLibrary}
                        disabled={creatingAssessment}
                        className="mt-4 flex items-center justify-center gap-2 w-full px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 disabled:opacity-50"
                      >
                        {creatingAssessment ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <Plus className="w-4 h-4" />
                        )}
                        {creatingAssessment ? "Adding..." : "Add Selected Assessment"}
                      </button>
                    )}
                  </div>

                  <div className="text-center text-muted-foreground text-sm">or</div>

                  <button
                    id="create-new-assessment-btn"
                    onClick={() => setShowNewAssessment(true)}
                    className="w-full p-4 border-2 border-dashed border-border rounded-xl hover:border-primary/50 hover:bg-primary/5 transition-all text-left"
                  >
                    <div className="flex items-center gap-3">
                      <Plus className="w-6 h-6 text-primary" />
                      <div>
                        <h4 className="font-semibold">Create New Assessment</h4>
                        <p className="text-sm text-muted-foreground">Paste task and evaluation JSON to create a new assessment</p>
                      </div>
                    </div>
                  </button>
                </div>
              ) : (
                <div id="new-assessment-form" className="space-y-6">
                  <div className="flex items-center justify-between">
                    <h3 className="font-semibold">Create New Assessment</h3>
                    <button
                      onClick={() => setShowNewAssessment(false)}
                      className="text-sm text-muted-foreground hover:text-foreground"
                    >
                      Back to library
                    </button>
                  </div>

                  <div>
                    <label className="text-sm font-medium mb-2 block">Tools Enabled</label>
                    <div className="flex flex-wrap gap-2">
                      {[
                        { id: "excalidraw", label: "Whiteboard" },
                        { id: "voice_recorder", label: "Voice Recorder" },
                      ].map((tool) => (
                        <button
                          key={tool.id}
                          id={`tool-toggle-${tool.id}`}
                          onClick={() => toggleTool(tool.id)}
                          className={`px-3 py-1.5 text-sm rounded-lg border transition-colors ${
                            toolsEnabled.includes(tool.id)
                              ? "border-primary bg-primary/10 text-primary"
                              : "border-border hover:border-primary/50"
                          }`}
                        >
                          {tool.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <label className="text-sm font-medium mb-1 block">
                      Task Definition JSON *
                      {taskJsonError && <span className="text-destructive ml-2">{taskJsonError}</span>}
                    </label>
                    <p className="text-xs text-muted-foreground mb-2">
                      Fields like <code className="bg-secondary px-1 rounded">scenario.title</code>, <code className="bg-secondary px-1 rounded">task_metadata.estimated_time</code>, <code className="bg-secondary px-1 rounded">task_metadata.seniority_level</code> are auto-inferred.
                    </p>
                    <textarea
                      id="task-definition-json-input"
                      value={taskDefinitionJson}
                      onChange={(e) => {
                        setTaskDefinitionJson(e.target.value);
                        if (e.target.value) validateAssessmentJson(e.target.value, "task");
                      }}
                      placeholder='{"scenario": {"title": "..."}, "task_metadata": {"estimated_time": 45, "seniority_level": "PM"}}'
                      rows={8}
                      className={`w-full px-3 py-2 border rounded-lg bg-zinc-900 text-zinc-100 font-mono text-sm focus:outline-none resize-y ${
                        taskJsonError ? "border-destructive" : "border-border focus:border-primary"
                      }`}
                    />
                  </div>

                  <div>
                    <label className="text-sm font-medium mb-1 block">
                      Evaluation Rubric JSON *
                      {evalJsonError && <span className="text-destructive ml-2">{evalJsonError}</span>}
                    </label>
                    <textarea
                      id="eval-rubric-json-input"
                      value={evalRubricJson}
                      onChange={(e) => {
                        setEvalRubricJson(e.target.value);
                        if (e.target.value) validateAssessmentJson(e.target.value, "eval");
                      }}
                      placeholder='{"rubric_metadata": {"task_title": "..."}, "evaluation_categories": [...]}'
                      rows={8}
                      className={`w-full px-3 py-2 border rounded-lg bg-zinc-900 text-zinc-100 font-mono text-sm focus:outline-none resize-y ${
                        evalJsonError ? "border-destructive" : "border-border focus:border-primary"
                      }`}
                    />
                  </div>

                  {taskDefinitionJson.trim() && !taskJsonError && (() => {
                    const inferred = inferFromJson(taskDefinitionJson, evalRubricJson);
                    return (
                      <div id="inferred-preview" className="bg-secondary/50 border border-border rounded-lg p-4">
                        <h4 className="text-sm font-medium mb-2">Inferred from JSON:</h4>
                        <div className="grid grid-cols-2 gap-2 text-sm">
                          <div><span className="text-muted-foreground">Title:</span> {inferred.title || <span className="italic text-muted-foreground">Not found</span>}</div>
                          <div><span className="text-muted-foreground">Duration:</span> {inferred.duration} mins</div>
                          <div><span className="text-muted-foreground">Seniority:</span> {inferred.role_seniority || <span className="italic text-muted-foreground">Not found</span>}</div>
                        </div>
                      </div>
                    );
                  })()}

                  <button
                    id="create-assessment-submit-btn"
                    onClick={handleCreateNewAssessment}
                    disabled={creatingAssessment || !taskDefinitionJson.trim() || !evalRubricJson.trim()}
                    className="flex items-center justify-center gap-2 w-full px-6 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 disabled:opacity-50"
                  >
                    {creatingAssessment ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Plus className="w-4 h-4" />
                    )}
                    {creatingAssessment ? "Creating..." : "Create & Add Assessment"}
                  </button>
                </div>
              )}

              {assessmentError && (
                <div className="mt-4 flex items-start gap-2 text-destructive text-sm">
                  <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                  <span>{assessmentError}</span>
                </div>
              )}

              <div id="assessment-actions" className="flex justify-between mt-8 pt-6 border-t border-border">
                <button
                  id="skip-assessment-btn"
                  onClick={handleSkipAssessment}
                  className="flex items-center gap-2 px-6 py-3 border border-border rounded-lg hover:bg-secondary transition-colors"
                >
                  <SkipForward className="w-4 h-4" />
                  Skip & Go to Editor
                </button>
                <p className="text-sm text-muted-foreground self-center">
                  You can always add assessments later from the plan editor
                </p>
              </div>
            </div>
          )}
        </main>
      </div>
    </AuthGuard>
  );
}
