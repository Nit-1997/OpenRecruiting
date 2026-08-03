"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Save,
  Loader2,
  FileJson,
  AlertCircle,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Clock,
  User,
  FileText,
} from "lucide-react";
import { AuthGuard } from "@/components/auth-guard";
import { AdminNav } from "@/components/admin-nav";
import { createClient } from "@/lib/supabase/client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
// V2 backend base — assessment-templates admin endpoints are ported to /api/v2/admin.
const API_V2_URL = process.env.NEXT_PUBLIC_API_V2_URL || "http://localhost:8004";

const DEFAULT_TASK_JSON = {
  version: "1.0",
  display: {
    title: "Assessment Task Title",
    description: "Brief description of the assessment task",
    role_seniority: "Mid-level"
  },
  context: {
    scenario_title: "Business Scenario",
    industry_domain: "Technology",
    role_position: "Product Manager",
    background: "Background context for the scenario...",
    challenge_statement: "The key challenge the candidate needs to address..."
  },
  requirements: {
    primary_objective: "What the candidate needs to accomplish",
    deliverables: [
      "First deliverable",
      "Second deliverable"
    ],
    output_format: "Whiteboard diagram with verbal explanation",
    expected_length: "15-20 minutes of content",
    audience: "Executive stakeholders"
  },
  guidelines: [
    "Guideline 1",
    "Guideline 2"
  ],
  skills_evaluated: [
    {
      skill_name: "Strategic Thinking",
      skill_type: "soft",
      priority: "must_have",
      assessment_approach: "How this skill will be evaluated"
    }
  ],
  tips_for_success: [
    "Tip 1",
    "Tip 2"
  ],
  resources: {
    metrics: [
      {
        name: "Key Metric",
        current_value: "100",
        trend: "Growing 10% MoM",
        context: "Additional context"
      }
    ],
    customer_quotes: [
      {
        source: "Customer Type",
        quote: "Customer feedback quote"
      }
    ],
    competitive_insights: [
      {
        competitor: "Competitor Name",
        insight: "Competitive insight"
      }
    ],
    links: [],
    additional_context: {
      team_composition: "Team details",
      constraints: ["Constraint 1"],
      timeline: "Timeline details",
      resources_available: "Available resources",
      success_stakes: "What success looks like"
    }
  },
  metadata: {
    estimated_time_minutes: 45,
    complexity_level: "intermediate",
    tools_enabled: ["excalidraw", "voice_recorder"]
  }
};

const DEFAULT_EVAL_JSON = {
  version: "1.0",
  metadata: {
    title: "Evaluation Rubric",
    role: "Product Manager",
    seniority: "Mid-level",
    total_points: 100,
    passing_threshold: 70
  },
  dimensions: [
    {
      id: "dim_1",
      title: "Strategic Thinking",
      weight_percentage: 40,
      max_points: 40,
      description: "Ability to think strategically about the problem",
      metrics: [
        {
          id: "metric_1_1",
          name: "Problem Analysis",
          max_points: 20,
          definition: "How well the candidate analyzes the problem",
          rubrics: [
            {
              level: "excellent",
              label: "Excellent",
              point_range: "18-20",
              min_points: 18,
              max_points: 20,
              description: "Outstanding problem analysis",
              indicators: ["Comprehensive analysis", "Clear insights"]
            },
            {
              level: "good",
              label: "Good",
              point_range: "14-17",
              min_points: 14,
              max_points: 17,
              description: "Good problem analysis",
              indicators: ["Solid analysis", "Good insights"]
            },
            {
              level: "adequate",
              label: "Adequate",
              point_range: "10-13",
              min_points: 10,
              max_points: 13,
              description: "Basic problem analysis",
              indicators: ["Basic analysis", "Some insights"]
            },
            {
              level: "poor",
              label: "Poor",
              point_range: "0-9",
              min_points: 0,
              max_points: 9,
              description: "Insufficient analysis",
              indicators: ["Lacks depth", "Missing key elements"]
            }
          ]
        }
      ]
    }
  ],
  guidelines: [
    {
      id: "guide_1",
      heading: "Evaluation Guideline",
      description: "How to apply this rubric"
    }
  ],
  bias_reminders: [
    "Evaluate based on demonstrated skills, not presentation style"
  ]
};

interface InferredData {
  title: string;
  description: string;
  role_seniority: string;
  time_limit_minutes: number;
  tools_enabled: string[];
}

function inferFromJson(taskJson: string, evalJson: string): InferredData {
  const defaults: InferredData = {
    title: "",
    description: "",
    role_seniority: "",
    time_limit_minutes: 45,
    tools_enabled: ["excalidraw", "voice_recorder"],
  };

  try {
    const task = JSON.parse(taskJson);
    defaults.title = task?.scenario?.title || task?.display?.title || "";
    defaults.description = task?.scenario?.challenge_statement || task?.task_requirements?.primary_objective || task?.display?.description || "";
    defaults.role_seniority = task?.task_metadata?.seniority_level || task?.display?.role_seniority || task?.context?.role_position || "";
    defaults.time_limit_minutes = task?.task_metadata?.estimated_time || task?.metadata?.estimated_time_minutes || 45;
    defaults.tools_enabled = task?.metadata?.tools_enabled || ["excalidraw", "voice_recorder"];
  } catch {
    // ignore parse errors
  }

  try {
    const evalData = JSON.parse(evalJson);
    if (!defaults.title && evalData?.rubric_metadata?.task_title) {
      defaults.title = evalData.rubric_metadata.task_title;
    }
    if (!defaults.role_seniority) {
      if (evalData?.rubric_metadata?.role_seniority) {
        defaults.role_seniority = evalData.rubric_metadata.role_seniority;
      } else if (evalData?.metadata?.role) {
        defaults.role_seniority = `${evalData.metadata.role} - ${evalData.metadata.seniority || ""}`.trim();
      }
    }
  } catch {
    // ignore parse errors
  }

  return defaults;
}

interface CollapsibleSectionProps {
  id: string;
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
}

function CollapsibleSection({ id, title, icon, children, defaultOpen = true }: CollapsibleSectionProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div id={id} className="bg-card border border-border rounded-xl overflow-hidden">
      <button
        id={`${id}-toggle`}
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center gap-3 p-4 hover:bg-secondary/50 transition-colors"
      >
        <span className="text-primary">{icon}</span>
        <span className="font-semibold flex-1 text-left">{title}</span>
        {isOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
      </button>
      {isOpen && <div id={`${id}-content`} className="p-4 pt-0 border-t border-border">{children}</div>}
    </div>
  );
}

export default function NewAssessmentPage() {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  const [status, setStatus] = useState<"draft" | "published">("draft");

  const [taskJson, setTaskJson] = useState(JSON.stringify(DEFAULT_TASK_JSON, null, 2));
  const [evalJson, setEvalJson] = useState(JSON.stringify(DEFAULT_EVAL_JSON, null, 2));
  const [taskJsonError, setTaskJsonError] = useState("");
  const [evalJsonError, setEvalJsonError] = useState("");

  const [inferred, setInferred] = useState<InferredData>(() => inferFromJson(taskJson, evalJson));
  const [toolsEnabled, setToolsEnabled] = useState<string[]>(["excalidraw", "voice_recorder"]);

  useEffect(() => {
    const newInferred = inferFromJson(taskJson, evalJson);
    setInferred(newInferred);
    if (newInferred.tools_enabled.length > 0) {
      setToolsEnabled(newInferred.tools_enabled);
    }
  }, [taskJson, evalJson]);

  const toggleTool = (toolId: string) => {
    setToolsEnabled((prev) =>
      prev.includes(toolId) ? prev.filter((t) => t !== toolId) : [...prev, toolId]
    );
  };

  const validateJson = (json: string, setter: (error: string) => void): boolean => {
    try {
      JSON.parse(json);
      setter("");
      return true;
    } catch (e) {
      setter(e instanceof Error ? e.message : "Invalid JSON");
      return false;
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    const taskValid = validateJson(taskJson, setTaskJsonError);
    const evalValid = validateJson(evalJson, setEvalJsonError);

    if (!taskValid || !evalValid) {
      setError("Please fix JSON validation errors");
      return;
    }

    const inferredData = inferFromJson(taskJson, evalJson);

    if (!inferredData.title.trim()) {
      setError("Task definition must include display.title");
      return;
    }

    try {
      setIsLoading(true);
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        router.push("/login");
        return;
      }

      const response = await fetch(`${API_V2_URL}/api/v2/admin/assessment-templates`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session.access_token}`,
        },
        body: JSON.stringify({
          title: inferredData.title,
          description: inferredData.description || null,
          role_seniority: inferredData.role_seniority || null,
          time_limit_minutes: inferredData.time_limit_minutes,
          tools_enabled: toolsEnabled,
          status,
          task_definition: JSON.parse(taskJson),
          evaluation_rubric: JSON.parse(evalJson),
        }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || "Failed to create template");
      }

      setSuccess(true);
      setTimeout(() => router.push("/assessments"), 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create template");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <AuthGuard>
      <div id="new-assessment-page" className="min-h-screen bg-secondary/30">
        <AdminNav />

        <main id="new-assessment-main" className="p-6 max-w-5xl mx-auto">
          <div id="new-assessment-header" className="mb-8">
            <Link
              href="/assessments"
              className="inline-flex items-center gap-2 text-muted-foreground hover:text-foreground mb-4"
            >
              <ArrowLeft className="w-4 h-4" />
              Back to Assessments
            </Link>
            <h1 id="new-assessment-title" className="text-3xl font-bold">Create Assessment Template</h1>
            <p className="text-muted-foreground mt-1">
              Provide the Task Definition and Evaluation Rubric JSONs. All other fields are inferred automatically.
            </p>
          </div>

          {success && (
            <div id="success-message" className="bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-400 border border-green-200 dark:border-green-800 rounded-lg p-4 mb-6 flex items-center gap-3">
              <CheckCircle className="w-5 h-5" />
              Template created successfully! Redirecting...
            </div>
          )}

          {error && (
            <div id="error-message" className="bg-destructive/10 text-destructive border border-destructive/20 rounded-lg p-4 mb-6 flex items-center gap-3">
              <AlertCircle className="w-5 h-5" />
              {error}
            </div>
          )}

          <form id="new-assessment-form" onSubmit={handleSubmit} className="space-y-6">
            <CollapsibleSection id="task-json-section" title="Task Definition (JSON)" icon={<FileJson className="w-5 h-5" />}>
              <div className="mt-4">
                <p className="text-sm text-muted-foreground mb-3">
                  Paste the task JSON. Fields like <code className="bg-secondary px-1 rounded">scenario.title</code>, <code className="bg-secondary px-1 rounded">task_metadata.seniority_level</code>, and <code className="bg-secondary px-1 rounded">task_metadata.estimated_time</code> are auto-inferred.
                </p>
                {taskJsonError && (
                  <div className="text-sm text-destructive bg-destructive/10 rounded-lg p-2 mb-2">
                    JSON Error: {taskJsonError}
                  </div>
                )}
                <textarea
                  id="task-json"
                  value={taskJson}
                  onChange={(e) => {
                    setTaskJson(e.target.value);
                    validateJson(e.target.value, setTaskJsonError);
                  }}
                  rows={20}
                  className={`w-full px-4 py-3 bg-zinc-900 text-zinc-100 font-mono text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50 resize-y ${
                    taskJsonError ? "border-destructive" : "border-border"
                  }`}
                  spellCheck={false}
                />
              </div>
            </CollapsibleSection>

            <CollapsibleSection id="eval-json-section" title="Evaluation Rubric (JSON)" icon={<FileJson className="w-5 h-5" />}>
              <div className="mt-4">
                <p className="text-sm text-muted-foreground mb-3">
                  Define the dimensions, metrics, and rubrics used to evaluate candidate responses.
                </p>
                {evalJsonError && (
                  <div className="text-sm text-destructive bg-destructive/10 rounded-lg p-2 mb-2">
                    JSON Error: {evalJsonError}
                  </div>
                )}
                <textarea
                  id="eval-json"
                  value={evalJson}
                  onChange={(e) => {
                    setEvalJson(e.target.value);
                    validateJson(e.target.value, setEvalJsonError);
                  }}
                  rows={20}
                  className={`w-full px-4 py-3 bg-zinc-900 text-zinc-100 font-mono text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50 resize-y ${
                    evalJsonError ? "border-destructive" : "border-border"
                  }`}
                  spellCheck={false}
                />
              </div>
            </CollapsibleSection>

            <div id="inferred-preview" className="bg-card border border-border rounded-xl p-4">
              <h3 className="font-semibold mb-3 flex items-center gap-2">
                <FileText className="w-4 h-4 text-primary" />
                Inferred from JSON
              </h3>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-muted-foreground">Title:</span>
                  <p className="font-medium">{inferred.title || <span className="text-muted-foreground italic">Not found in JSON</span>}</p>
                </div>
                <div>
                  <span className="text-muted-foreground">Role / Seniority:</span>
                  <p className="font-medium flex items-center gap-1">
                    <User className="w-3 h-3" />
                    {inferred.role_seniority || <span className="text-muted-foreground italic">Not found</span>}
                  </p>
                </div>
                <div>
                  <span className="text-muted-foreground">Description:</span>
                  <p className="font-medium line-clamp-2">{inferred.description || <span className="text-muted-foreground italic">Not found</span>}</p>
                </div>
                <div>
                  <span className="text-muted-foreground">Time Limit:</span>
                  <p className="font-medium flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {inferred.time_limit_minutes} minutes
                  </p>
                </div>
                <div className="col-span-2">
                  <span className="text-muted-foreground">Tools Enabled:</span>
                  <p className="font-medium">
                    {toolsEnabled.map((t) => t === "excalidraw" ? "Whiteboard" : t === "voice_recorder" ? "Voice Recorder" : t).join(", ") || "None"}
                  </p>
                </div>
              </div>
            </div>

            <div id="tools-section" className="bg-card border border-border rounded-xl p-4">
              <label className="block text-sm font-medium mb-2">Tools Enabled</label>
              <p className="text-sm text-muted-foreground mb-3">
                Select which tools candidates will have access to during the assessment.
              </p>
              <div className="flex flex-wrap gap-2">
                {[
                  { id: "excalidraw", label: "Whiteboard" },
                  { id: "voice_recorder", label: "Voice Recorder" },
                ].map((tool) => (
                  <button
                    key={tool.id}
                    id={`tool-toggle-${tool.id}`}
                    type="button"
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

            <div id="status-section" className="bg-card border border-border rounded-xl p-4">
              <label className="block text-sm font-medium mb-2">Status</label>
              <div className="flex gap-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="status"
                    value="draft"
                    checked={status === "draft"}
                    onChange={() => setStatus("draft")}
                    className="w-4 h-4 text-primary"
                  />
                  <span>Draft</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="status"
                    value="published"
                    checked={status === "published"}
                    onChange={() => setStatus("published")}
                    className="w-4 h-4 text-primary"
                  />
                  <span>Published</span>
                </label>
              </div>
            </div>

            <div id="form-actions" className="flex items-center justify-end gap-4 pt-4">
              <Link
                href="/assessments"
                className="px-4 py-2 rounded-lg hover:bg-secondary transition-colors"
              >
                Cancel
              </Link>
              <button
                type="submit"
                disabled={isLoading || success}
                className="flex items-center gap-2 px-6 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 disabled:opacity-50 transition-colors"
              >
                {isLoading ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Creating...
                  </>
                ) : (
                  <>
                    <Save className="w-4 h-4" />
                    Create Template
                  </>
                )}
              </button>
            </div>
          </form>
        </main>
      </div>
    </AuthGuard>
  );
}
