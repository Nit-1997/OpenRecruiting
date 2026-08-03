"use client";

import { useState, useEffect, use } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Save,
  Loader2,
  FileJson,
  Clock,
  AlertCircle,
  CheckCircle,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { AuthGuard } from "@/components/auth-guard";
import { AdminNav } from "@/components/admin-nav";
import { createClient } from "@/lib/supabase/client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
// V2 backend base — assessment-templates admin endpoints are ported to /api/v2/admin.
const API_V2_URL = process.env.NEXT_PUBLIC_API_V2_URL || "http://localhost:8004";

const AVAILABLE_TOOLS = [
  { id: "excalidraw", label: "Whiteboard" },
  { id: "voice_recorder", label: "Voice Recorder" },
];

function inferFromJson(taskJson: string, evalJson: string) {
  const defaults = {
    title: "",
    description: "",
    role_seniority: "",
    time_limit_minutes: 45,
  };
  try {
    const task = JSON.parse(taskJson);
    defaults.title = task?.scenario?.title || task?.display?.title || "";
    defaults.description = task?.scenario?.challenge_statement || task?.task_requirements?.primary_objective || task?.display?.description || "";
    defaults.role_seniority = task?.task_metadata?.seniority_level || task?.display?.role_seniority || task?.context?.role_position || "";
    defaults.time_limit_minutes = task?.task_metadata?.estimated_time || task?.metadata?.estimated_time_minutes || 45;
  } catch { }
  try {
    const evalData = JSON.parse(evalJson);
    if (!defaults.title && evalData?.rubric_metadata?.task_title) {
      defaults.title = evalData.rubric_metadata.task_title;
    }
    if (!defaults.role_seniority && evalData?.rubric_metadata?.role_seniority) {
      defaults.role_seniority = evalData.rubric_metadata.role_seniority;
    }
  } catch { }
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

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function EditAssessmentPage({ params }: PageProps) {
  const { id } = use(params);
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  const [toolsEnabled, setToolsEnabled] = useState<string[]>(["excalidraw", "voice_recorder"]);
  const [status, setStatus] = useState<"draft" | "published" | "archived">("draft");
  const [version, setVersion] = useState("1.0");

  const [taskJson, setTaskJson] = useState("");
  const [evalJson, setEvalJson] = useState("");
  const [taskJsonError, setTaskJsonError] = useState("");
  const [evalJsonError, setEvalJsonError] = useState("");

  const inferred = inferFromJson(taskJson, evalJson);

  useEffect(() => {
    const fetchTemplate = async () => {
      try {
        const supabase = createClient();
        const { data: { session } } = await supabase.auth.getSession();

        if (!session?.access_token) {
          router.push("/login");
          return;
        }

        const response = await fetch(`${API_V2_URL}/api/v2/admin/assessment-templates/${id}`, {
          headers: { Authorization: `Bearer ${session.access_token}` },
        });

        if (!response.ok) {
          throw new Error("Failed to fetch template");
        }

        const template = await response.json();

        setToolsEnabled(template.tools_enabled || ["excalidraw", "voice_recorder"]);
        setStatus(template.status);
        setVersion(template.version);
        setTaskJson(JSON.stringify(template.task_definition, null, 2));
        setEvalJson(JSON.stringify(template.evaluation_rubric, null, 2));
      } catch (err) {
        console.error("Error fetching template:", err);
        setError("Failed to load template");
      } finally {
        setIsLoading(false);
      }
    };

    fetchTemplate();
  }, [id, router]);

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

  const handleToolToggle = (toolId: string) => {
    setToolsEnabled((prev) =>
      prev.includes(toolId) ? prev.filter((t) => t !== toolId) : [...prev, toolId]
    );
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

    const inferredValues = inferFromJson(taskJson, evalJson);
    if (!inferredValues.title.trim()) {
      setError("Task definition must include scenario.title or display.title");
      return;
    }

    try {
      setIsSaving(true);
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        router.push("/login");
        return;
      }

      const response = await fetch(`${API_V2_URL}/api/v2/admin/assessment-templates/${id}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session.access_token}`,
        },
        body: JSON.stringify({
          title: inferredValues.title,
          description: inferredValues.description || null,
          role_seniority: inferredValues.role_seniority || null,
          time_limit_minutes: inferredValues.time_limit_minutes,
          tools_enabled: toolsEnabled,
          status,
          task_definition: JSON.parse(taskJson),
          evaluation_rubric: JSON.parse(evalJson),
        }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || "Failed to update template");
      }

      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update template");
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) {
    return (
      <AuthGuard>
        <div id="edit-assessment-loading" className="min-h-screen bg-secondary/30">
          <AdminNav />
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
          </div>
        </div>
      </AuthGuard>
    );
  }

  return (
    <AuthGuard>
      <div id="edit-assessment-page" className="min-h-screen bg-secondary/30">
        <AdminNav />

        <main id="edit-assessment-main" className="p-6 max-w-5xl mx-auto">
          {/* Header */}
          <div id="edit-assessment-header" className="mb-8">
            <Link
              href="/assessments"
              className="inline-flex items-center gap-2 text-muted-foreground hover:text-foreground mb-4"
            >
              <ArrowLeft className="w-4 h-4" />
              Back to Assessments
            </Link>
            <div className="flex items-center justify-between">
              <div>
                <h1 id="edit-assessment-title" className="text-3xl font-bold">Edit Assessment Template</h1>
                <p className="text-muted-foreground mt-1">Version {version}</p>
              </div>
            </div>
          </div>

          {/* Success Message */}
          {success && (
            <div id="success-message" className="bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-400 border border-green-200 dark:border-green-800 rounded-lg p-4 mb-6 flex items-center gap-3">
              <CheckCircle className="w-5 h-5" />
              Template saved successfully!
            </div>
          )}

          {/* Error Message */}
          {error && (
            <div id="error-message" className="bg-destructive/10 text-destructive border border-destructive/20 rounded-lg p-4 mb-6 flex items-center gap-3">
              <AlertCircle className="w-5 h-5" />
              {error}
            </div>
          )}

          <form id="edit-assessment-form" onSubmit={handleSubmit} className="space-y-6">
            {/* Task Definition JSON */}
            <CollapsibleSection id="task-json-section" title="Task Definition (JSON)" icon={<FileJson className="w-5 h-5" />}>
              <div className="mt-4">
                <p className="text-sm text-muted-foreground mb-3">
                  Fields like <code className="bg-secondary px-1 rounded">scenario.title</code>, <code className="bg-secondary px-1 rounded">task_metadata.estimated_time</code>, and <code className="bg-secondary px-1 rounded">task_metadata.seniority_level</code> are auto-inferred.
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

            {/* Evaluation Rubric JSON */}
            <CollapsibleSection id="eval-json-section" title="Evaluation Rubric (JSON)" icon={<FileJson className="w-5 h-5" />}>
              <div className="mt-4">
                <p className="text-sm text-muted-foreground mb-3">
                  Define the dimensions, metrics, and rubrics used to evaluate candidate responses
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

            {/* Tools and Status */}
            <div id="tools-status-section" className="bg-card border border-border rounded-xl p-4 space-y-4">
              <div>
                <label className="block text-sm font-medium mb-2">Tools Enabled</label>
                <div className="flex flex-wrap gap-2">
                  {AVAILABLE_TOOLS.map((tool) => (
                    <button
                      key={tool.id}
                      id={`tool-toggle-${tool.id}`}
                      type="button"
                      onClick={() => handleToolToggle(tool.id)}
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
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="status"
                      value="archived"
                      checked={status === "archived"}
                      onChange={() => setStatus("archived")}
                      className="w-4 h-4 text-primary"
                    />
                    <span>Archived</span>
                  </label>
                </div>
              </div>
            </div>

            {/* Inferred Preview */}
            <div id="inferred-preview" className="bg-card border border-border rounded-xl p-4">
              <h3 className="font-semibold mb-3">Inferred from JSON</h3>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-muted-foreground">Title:</span>
                  <p className="font-medium">{inferred.title || <span className="text-muted-foreground italic">Not found in JSON</span>}</p>
                </div>
                <div>
                  <span className="text-muted-foreground">Duration:</span>
                  <p className="font-medium flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {inferred.time_limit_minutes} minutes
                  </p>
                </div>
                <div>
                  <span className="text-muted-foreground">Role / Seniority:</span>
                  <p className="font-medium">{inferred.role_seniority || <span className="text-muted-foreground italic">Not found</span>}</p>
                </div>
                <div>
                  <span className="text-muted-foreground">Tools:</span>
                  <p className="font-medium">{toolsEnabled.map((t) => t === "excalidraw" ? "Whiteboard" : t === "voice_recorder" ? "Voice Recorder" : t).join(", ") || "None"}</p>
                </div>
              </div>
            </div>

            {/* Submit */}
            <div id="form-actions" className="flex items-center justify-end gap-4 pt-4">
              <Link
                href="/assessments"
                className="px-4 py-2 rounded-lg hover:bg-secondary transition-colors"
              >
                Cancel
              </Link>
              <button
                type="submit"
                disabled={isSaving}
                className="flex items-center gap-2 px-6 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 disabled:opacity-50 transition-colors"
              >
                {isSaving ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Saving...
                  </>
                ) : (
                  <>
                    <Save className="w-4 h-4" />
                    Save Changes
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
