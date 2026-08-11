"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  Building2,
  ArrowLeft,
  Check,
  Plus,
  X,
  Pencil,
  Trash2,
  ChevronRight,
  MapPin,
  Briefcase,
  LogOut,
  Loader2,
  Save,
  Clock,
  GripVertical,
  FileJson,
  ClipboardList,
  Users,
  AlertCircle,
} from "lucide-react";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { AuthGuard } from "@/components/auth-guard";
import { createClient } from "@/lib/supabase/client";
import { getRuntimeConfig } from "@/lib/runtime-config";

interface FeedbackQuestion {
  id: string;
  round_id: string;
  question_number: number;
  heading: string;
  description?: string;
}

interface Guideline {
  title: string;
  description: string;
}

interface AssessmentTemplate {
  id: string;
  title: string;
  description: string | null;
  role_seniority: string | null;
  tools_enabled: string[];
  time_limit_minutes: number;
  task_definition: object;
  evaluation_rubric: object;
  status: "draft" | "published" | "archived";
  version: string;
}

interface Round {
  id: string;
  requisition_id: string;
  round_number: number;
  name: string;
  category: string;
  duration_minutes: number;
  duration_display: string;
  description: string;
  skills: string[];
  guidelines: Guideline[];
  feedback_questions: FeedbackQuestion[];
  round_type?: "interview" | "assessment";
  assessment_template_id?: string | null;
  assessment_template?: AssessmentTemplate | null;
}

interface InterviewPlan {
  requisition_id: string;
  total_rounds: number;
  total_duration_minutes: number;
  total_duration_display: string;
  rounds: Round[];
}

interface Requisition {
  id: string;
  organization_id: string;
  role_title: string;
  role_location: string | null;
  experience_display: string;
  status: string;
}

interface Organization {
  id: string;
  name: string;
}

interface AssessmentRoundEditorProps {
  round: Round;
  onSave: () => Promise<void>;
  onSaveAll: () => Promise<void>;
  onNextRound: () => void;
  onRefresh: () => Promise<void>;
  savingRoundId: string | null;
  savingAll: boolean;
  isLastRound: boolean;
  apiUrl: string;
}

interface TaskJson {
  task_metadata?: {
    skills_tested?: Array<{ skill_name: string; skill_priority: string; skill_type: string; assessment_approach: string }>;
    estimated_time?: number;
    seniority_level?: string;
    output_format_required?: string;
    selection_rationale?: string;
    complexity_calibration?: string;
  };
  scenario?: {
    title?: string;
    industry_domain?: string;
    role_position?: string;
    context?: string;
    challenge_statement?: string;
  };
  supporting_data?: {
    customer_quotes?: Array<{ source: string; quote: string }>;
    key_metrics?: Array<{ metric_name: string; current_value: string; trend: string; context: string; segmentation?: string }>;
    competitive_insights?: Array<{ insight: string }>;
    additional_context?: { resources_available?: string; constraints?: string[]; team_composition?: string; timeline?: string; success_context?: string };
  };
  task_requirements?: {
    primary_objective?: string;
    key_guidelines?: string[];
    output_specifications?: { format?: string; expected_length?: string; required_sections?: string[]; audience?: string; tone_guidance?: string };
    evaluation_focus?: string[];
  };
}

interface EvalJson {
  rubric_metadata?: {
    task_title?: string;
    role_seniority?: string;
    total_possible_points?: number;
    passing_threshold_percentage?: number;
    calibration_notes?: string;
  };
  evaluation_categories?: Array<{
    category_name: string;
    category_weight_percentage: number;
    category_description: string;
    criteria: Array<{
      criterion_id: string;
      criterion_name: string;
      criterion_description: string;
      max_points: number;
      weight_rationale?: string;
      scoring_rubric: {
        excellent?: { point_range: string; description: string; indicators?: string[] };
        good?: { point_range: string; description: string; indicators?: string[] };
        adequate?: { point_range: string; description: string; indicators?: string[] };
        poor?: { point_range: string; description: string; indicators?: string[] };
      };
      common_pitfalls?: string[];
      ai_detection_flags?: string[];
    }>;
  }>;
  holistic_assessment_guidelines?: {
    balance_note?: string;
    seniority_expectations?: string;
    time_constraint_note?: string;
    bias_reminders?: string[];
  };
}

function AssessmentRoundEditor({
  round,
  onSave,
  onSaveAll,
  onNextRound,
  onRefresh,
  savingRoundId,
  savingAll,
  isLastRound,
  apiUrl,
}: AssessmentRoundEditorProps) {
  const [activeTab, setActiveTab] = useState<"task" | "evaluation">("task");
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set());
  const [expandedCriteria, setExpandedCriteria] = useState<Set<string>>(new Set());
  const [expandedMetrics, setExpandedMetrics] = useState<Set<number>>(new Set());
  const [showSandboxModal, setShowSandboxModal] = useState(false);
  const [savingTemplate, setSavingTemplate] = useState(false);
  const [openingPreview, setOpeningPreview] = useState(false);
  const template = round.assessment_template;
  const ASSESSMENT_UI_URL = getRuntimeConfig().assessmentUiUrl || "http://localhost:3002";

  const [taskData, setTaskData] = useState<TaskJson | null>(template?.task_definition as TaskJson | null);
  const [evalData, setEvalData] = useState<EvalJson | null>(template?.evaluation_rubric as EvalJson | null);

  useEffect(() => {
    setTaskData(template?.task_definition as TaskJson | null);
    setEvalData(template?.evaluation_rubric as EvalJson | null);
  }, [template]);

  const updateTaskField = (path: string[], value: string | number) => {
    const newData = taskData ? JSON.parse(JSON.stringify(taskData)) : {};
    let current: Record<string, unknown> = newData;
    for (let i = 0; i < path.length - 1; i++) {
      if (!current[path[i]]) current[path[i]] = {};
      current = current[path[i]] as Record<string, unknown>;
    }
    current[path[path.length - 1]] = value;
    setTaskData(newData);
  };

  const updateTaskGuidelines = (guidelines: string[]) => {
    const newData = taskData ? JSON.parse(JSON.stringify(taskData)) : {};
    if (!newData.task_requirements) newData.task_requirements = {};
    newData.task_requirements.key_guidelines = guidelines;
    setTaskData(newData);
  };

  const updateSkill = (idx: number, field: string, value: string) => {
    const newData = taskData ? JSON.parse(JSON.stringify(taskData)) : {};
    if (!newData.task_metadata) newData.task_metadata = {};
    if (!newData.task_metadata.skills_tested) newData.task_metadata.skills_tested = [];
    if (newData.task_metadata.skills_tested[idx]) {
      newData.task_metadata.skills_tested[idx][field] = value;
    }
    setTaskData(newData);
  };

  const removeSkill = (idx: number) => {
    const newData = taskData ? JSON.parse(JSON.stringify(taskData)) : {};
    if (newData.task_metadata?.skills_tested) {
      newData.task_metadata.skills_tested = newData.task_metadata.skills_tested.filter((_: unknown, i: number) => i !== idx);
    }
    setTaskData(newData);
  };

  const addSkill = () => {
    const newData = taskData ? JSON.parse(JSON.stringify(taskData)) : {};
    if (!newData.task_metadata) newData.task_metadata = {};
    if (!newData.task_metadata.skills_tested) newData.task_metadata.skills_tested = [];
    newData.task_metadata.skills_tested.push({ skill_name: "", skill_priority: "good_to_have", skill_type: "", assessment_approach: "" });
    setTaskData(newData);
  };

  const updateMetric = (idx: number, field: string, value: string) => {
    const newData = taskData ? JSON.parse(JSON.stringify(taskData)) : {};
    if (!newData.supporting_data) newData.supporting_data = {};
    if (!newData.supporting_data.key_metrics) newData.supporting_data.key_metrics = [];
    if (newData.supporting_data.key_metrics[idx]) {
      newData.supporting_data.key_metrics[idx][field] = value;
    }
    setTaskData(newData);
  };

  const removeMetric = (idx: number) => {
    const newData = taskData ? JSON.parse(JSON.stringify(taskData)) : {};
    if (newData.supporting_data?.key_metrics) {
      newData.supporting_data.key_metrics = newData.supporting_data.key_metrics.filter((_: unknown, i: number) => i !== idx);
    }
    setTaskData(newData);
  };

  const addMetric = () => {
    const newData = taskData ? JSON.parse(JSON.stringify(taskData)) : {};
    if (!newData.supporting_data) newData.supporting_data = {};
    if (!newData.supporting_data.key_metrics) newData.supporting_data.key_metrics = [];
    newData.supporting_data.key_metrics.push({ metric_name: "", current_value: "", trend: "", context: "" });
    setTaskData(newData);
  };

  const updateEvalMetadata = (field: string, value: string | number) => {
    const newData = evalData ? JSON.parse(JSON.stringify(evalData)) : {};
    if (!newData.rubric_metadata) newData.rubric_metadata = {};
    newData.rubric_metadata[field] = value;
    setEvalData(newData);
  };

  const updateEvalCategory = (categoryIdx: number, field: string, value: string | number) => {
    const newData = evalData ? JSON.parse(JSON.stringify(evalData)) : {};
    if (!newData.evaluation_categories) newData.evaluation_categories = [];
    if (newData.evaluation_categories[categoryIdx]) {
      newData.evaluation_categories[categoryIdx][field] = value;
    }
    setEvalData(newData);
  };

  const updateEvalCriterion = (categoryIdx: number, criterionIdx: number, field: string, value: string | number) => {
    const newData = evalData ? JSON.parse(JSON.stringify(evalData)) : {};
    if (newData.evaluation_categories?.[categoryIdx]?.criteria?.[criterionIdx]) {
      newData.evaluation_categories[categoryIdx].criteria[criterionIdx][field] = value;
    }
    setEvalData(newData);
  };

  const updateScoringRubric = (categoryIdx: number, criterionIdx: number, level: string, field: string, value: string) => {
    const newData = evalData ? JSON.parse(JSON.stringify(evalData)) : {};
    if (newData.evaluation_categories?.[categoryIdx]?.criteria?.[criterionIdx]?.scoring_rubric?.[level]) {
      newData.evaluation_categories[categoryIdx].criteria[criterionIdx].scoring_rubric[level][field] = value;
    }
    setEvalData(newData);
  };

  const saveTemplateChanges = async (): Promise<boolean> => {
    if (!template?.id) return false;
    setSavingTemplate(true);
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) return false;

      const response = await fetch(`${apiUrl}/api/v2/admin/assessment-templates/${template.id}`, {
        method: "PUT",
        headers: {
          "Authorization": `Bearer ${session.access_token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          task_definition: taskData,
          evaluation_rubric: evalData,
        }),
      });

      if (!response.ok) throw new Error("Failed to save template");
      return true;
    } catch (err) {
      console.error("Failed to save template:", err);
      return false;
    } finally {
      setSavingTemplate(false);
    }
  };

  const openPreview = async () => {
    if (!template?.id) return;
    setOpeningPreview(true);
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) {
        alert("Please log in to preview the assessment");
        return;
      }
      const previewUrl = `${ASSESSMENT_UI_URL}/preview/${template.id}?token=${session.access_token}`;
      window.open(previewUrl, "_blank");
      setShowSandboxModal(false);
    } catch (err) {
      console.error("Failed to open preview:", err);
    } finally {
      setOpeningPreview(false);
    }
  };

  const handleSave = async () => {
    const success = await saveTemplateChanges();
    if (success) {
      await onRefresh();
    }
  };

  const handleSaveAll = async () => {
    const success = await saveTemplateChanges();
    if (success) {
      await onSaveAll();
      await onRefresh();
    }
  };

  const toggleMetric = (idx: number) => {
    setExpandedMetrics(prev => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const toggleCategory = (catName: string) => {
    setExpandedCategories(prev => {
      const next = new Set(prev);
      if (next.has(catName)) next.delete(catName);
      else next.add(catName);
      return next;
    });
  };

  const toggleCriterion = (critId: string) => {
    setExpandedCriteria(prev => {
      const next = new Set(prev);
      if (next.has(critId)) next.delete(critId);
      else next.add(critId);
      return next;
    });
  };

  const renderTaskTab = () => {
    if (!taskData) {
      return (
        <div id="empty-task" className="text-center py-12 text-muted-foreground">
          <FileJson className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p>No task definition configured</p>
        </div>
      );
    }

    const scenario = taskData.scenario;
    const metadata = taskData.task_metadata;
    const requirements = taskData.task_requirements;
    const supportingData = taskData.supporting_data;

    return (
      <div id="task-content" className="space-y-6">
        <div id="task-header-section" className="text-center border-b border-border pb-6">
          <input
            id="task-title-input"
            type="text"
            value={scenario?.title || ""}
            onChange={(e) => updateTaskField(["scenario", "title"], e.target.value)}
            placeholder="Task Title"
            className="text-2xl font-bold mb-2 bg-transparent border-none text-center w-full focus:outline-none focus:ring-2 focus:ring-primary/20 rounded px-2"
          />
          <input
            id="task-domain-input"
            type="text"
            value={scenario?.industry_domain || ""}
            onChange={(e) => updateTaskField(["scenario", "industry_domain"], e.target.value)}
            placeholder="Industry Domain"
            className="text-sm text-muted-foreground bg-transparent border-none text-center w-full focus:outline-none focus:ring-2 focus:ring-primary/20 rounded px-2"
          />
        </div>

        <div id="task-context-section" className="bg-secondary/30 rounded-xl p-6">
          <h3 className="font-semibold mb-3">Context</h3>
          <textarea
            id="task-context-input"
            value={scenario?.context || ""}
            onChange={(e) => updateTaskField(["scenario", "context"], e.target.value)}
            placeholder="Enter context..."
            className="text-sm whitespace-pre-wrap leading-relaxed w-full min-h-[120px] bg-transparent border border-border rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-primary/20 resize-y"
          />
        </div>

        <div id="task-challenge-section" className="relative rounded-xl overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-r from-amber-500/20 to-orange-500/20" />
          <div className="relative border-l-4 border-amber-500 bg-card p-6">
            <div className="flex items-center gap-2 mb-3">
              <div className="w-8 h-8 rounded-full bg-amber-500/20 flex items-center justify-center">
                <AlertCircle className="w-4 h-4 text-amber-600 dark:text-amber-400" />
              </div>
              <h3 className="font-bold text-lg text-amber-700 dark:text-amber-300">The Challenge</h3>
            </div>
            <textarea
              id="task-challenge-input"
              value={scenario?.challenge_statement || ""}
              onChange={(e) => updateTaskField(["scenario", "challenge_statement"], e.target.value)}
              placeholder="Enter challenge statement..."
              className="text-sm leading-relaxed w-full min-h-[80px] bg-transparent border border-amber-300 dark:border-amber-700 rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-amber-500/20 resize-y"
            />
          </div>
        </div>

        <div id="task-requirements-section">
          <h3 className="font-semibold mb-3">Requirements</h3>
          <div className="bg-secondary/30 rounded-xl p-6">
            <textarea
              id="task-objective-input"
              value={requirements?.primary_objective || ""}
              onChange={(e) => updateTaskField(["task_requirements", "primary_objective"], e.target.value)}
              placeholder="Enter primary objective..."
              className="text-sm mb-4 w-full min-h-[60px] bg-transparent border border-border rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-primary/20 resize-y"
            />
            {requirements?.key_guidelines && requirements.key_guidelines.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground mb-2">Key Guidelines</p>
                {requirements.key_guidelines.map((guideline, idx) => (
                  <div key={idx} className="flex gap-3 items-start">
                    <span className="w-5 h-5 rounded-full bg-primary/10 text-primary flex items-center justify-center text-xs flex-shrink-0 mt-2">{idx + 1}</span>
                    <input
                      id={`task-guideline-${idx}`}
                      type="text"
                      value={guideline}
                      onChange={(e) => {
                        const newGuidelines = [...(requirements.key_guidelines || [])];
                        newGuidelines[idx] = e.target.value;
                        updateTaskGuidelines(newGuidelines);
                      }}
                      className="flex-1 text-sm bg-transparent border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/20"
                    />
                    <button
                      onClick={() => {
                        const newGuidelines = (requirements.key_guidelines || []).filter((_, i) => i !== idx);
                        updateTaskGuidelines(newGuidelines);
                      }}
                      className="p-2 text-destructive hover:bg-destructive/10 rounded"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                ))}
                <button
                  onClick={() => updateTaskGuidelines([...(requirements.key_guidelines || []), ""])}
                  className="flex items-center gap-2 text-sm text-primary hover:underline mt-2"
                >
                  <Plus className="w-4 h-4" /> Add Guideline
                </button>
              </div>
            )}
            {(!requirements?.key_guidelines || requirements.key_guidelines.length === 0) && (
              <button
                onClick={() => updateTaskGuidelines([""])}
                className="flex items-center gap-2 text-sm text-primary hover:underline"
              >
                <Plus className="w-4 h-4" /> Add Guidelines
              </button>
            )}
          </div>
        </div>

        <div id="task-skills-section">
          <h3 className="font-semibold mb-3">Skills Evaluated</h3>
          <div className="space-y-3">
            {(metadata?.skills_tested || []).map((skill, idx) => (
              <div key={idx} className="bg-secondary/30 rounded-lg p-4">
                <div className="flex items-start gap-3">
                  <div className="flex-1 space-y-2">
                    <div className="flex items-center gap-2">
                      <input
                        id={`skill-name-${idx}`}
                        type="text"
                        value={skill.skill_name}
                        onChange={(e) => updateSkill(idx, "skill_name", e.target.value)}
                        placeholder="Skill name"
                        className="flex-1 text-sm font-medium bg-transparent border border-border rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-primary/20"
                      />
                      <select
                        id={`skill-priority-${idx}`}
                        value={skill.skill_priority || "good_to_have"}
                        onChange={(e) => updateSkill(idx, "skill_priority", e.target.value)}
                        className="text-xs px-2 py-1 rounded border border-border bg-transparent focus:outline-none focus:ring-2 focus:ring-primary/20"
                      >
                        <option value="must_have">Must Have</option>
                        <option value="good_to_have">Good to Have</option>
                      </select>
                      <input
                        id={`skill-type-${idx}`}
                        type="text"
                        value={skill.skill_type || ""}
                        onChange={(e) => updateSkill(idx, "skill_type", e.target.value)}
                        placeholder="Type"
                        className="w-24 text-xs bg-transparent border border-border rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-primary/20"
                      />
                      <button
                        onClick={() => removeSkill(idx)}
                        className="p-1 text-destructive hover:bg-destructive/10 rounded"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                    <input
                      id={`skill-approach-${idx}`}
                      type="text"
                      value={skill.assessment_approach || ""}
                      onChange={(e) => updateSkill(idx, "assessment_approach", e.target.value)}
                      placeholder="Assessment approach"
                      className="w-full text-xs bg-transparent border border-border rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-primary/20"
                    />
                  </div>
                </div>
              </div>
            ))}
            <button
              onClick={addSkill}
              className="flex items-center gap-2 text-sm text-primary hover:underline"
            >
              <Plus className="w-4 h-4" /> Add Skill
            </button>
          </div>
        </div>

        <div id="task-metrics-section">
          <h3 className="font-semibold mb-3">Key Metrics</h3>
          <div className="space-y-2">
            {(supportingData?.key_metrics || []).map((metric, idx) => {
              const isExpanded = expandedMetrics.has(idx);
              return (
                <div key={idx} className="border border-border rounded-lg overflow-hidden">
                  <div className="flex items-center justify-between p-4">
                    <div className="flex items-center gap-3 flex-1">
                      <input
                        id={`metric-name-${idx}`}
                        type="text"
                        value={metric.metric_name}
                        onChange={(e) => updateMetric(idx, "metric_name", e.target.value)}
                        placeholder="Metric name"
                        className="font-medium text-sm bg-transparent border border-border rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-primary/20"
                      />
                      <input
                        id={`metric-value-${idx}`}
                        type="text"
                        value={metric.current_value}
                        onChange={(e) => updateMetric(idx, "current_value", e.target.value)}
                        placeholder="Value"
                        className="w-24 text-sm font-mono bg-primary/10 px-2 py-1 rounded border border-border focus:outline-none focus:ring-2 focus:ring-primary/20"
                      />
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => removeMetric(idx)}
                        className="p-1 text-destructive hover:bg-destructive/10 rounded"
                      >
                        <X className="w-4 h-4" />
                      </button>
                      <button
                        id={`metric-toggle-${idx}`}
                        onClick={() => toggleMetric(idx)}
                        className="p-1 hover:bg-secondary rounded"
                      >
                        <ChevronRight className={`w-4 h-4 transition-transform ${isExpanded ? "rotate-90" : ""}`} />
                      </button>
                    </div>
                  </div>
                  {isExpanded && (
                    <div id={`metric-content-${idx}`} className="border-t border-border p-4 bg-secondary/20 space-y-3">
                      <div>
                        <p className="text-xs font-medium text-muted-foreground mb-1">Trend</p>
                        <input
                          id={`metric-trend-${idx}`}
                          type="text"
                          value={metric.trend || ""}
                          onChange={(e) => updateMetric(idx, "trend", e.target.value)}
                          placeholder="Trend"
                          className="w-full text-sm bg-transparent border border-border rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-primary/20"
                        />
                      </div>
                      <div>
                        <p className="text-xs font-medium text-muted-foreground mb-1">Context</p>
                        <textarea
                          id={`metric-context-${idx}`}
                          value={metric.context || ""}
                          onChange={(e) => updateMetric(idx, "context", e.target.value)}
                          placeholder="Context"
                          className="w-full text-sm bg-transparent border border-border rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-primary/20 min-h-[60px] resize-y"
                        />
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
            <button
              onClick={addMetric}
              className="flex items-center gap-2 text-sm text-primary hover:underline"
            >
              <Plus className="w-4 h-4" /> Add Metric
            </button>
          </div>
        </div>

        <div id="task-sandbox-section" className="pt-4 border-t border-border">
          <button
            id="try-sandbox-btn"
            onClick={() => setShowSandboxModal(true)}
            className="w-full py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors font-medium"
          >
            Try Out In Sandbox
          </button>
        </div>

        {showSandboxModal && (
          <div id="sandbox-modal" className="fixed inset-0 z-50 flex items-center justify-center">
            <div className="absolute inset-0 bg-black/50" onClick={() => setShowSandboxModal(false)} />
            <div className="relative bg-card rounded-xl shadow-xl max-w-lg w-full mx-4 p-6">
              <h3 className="text-lg font-semibold mb-2">Sandbox Preview</h3>
              <p className="text-muted-foreground mb-4">
                The sandbox environment allows candidates to complete this assessment with access to the configured tools.
              </p>
              <div className="bg-secondary/30 rounded-lg p-4 mb-4">
                <p className="text-sm font-medium mb-2">Enabled Tools:</p>
                <div className="flex flex-wrap gap-2">
                  {(template?.tools_enabled || ["excalidraw"]).map((tool) => (
                    <span key={tool} className="px-2 py-1 text-xs bg-primary/10 text-primary rounded">
                      {tool === "excalidraw" ? "Whiteboard" : tool === "voice_recorder" ? "Voice Recorder" : tool.replace(/_/g, " ")}
                    </span>
                  ))}
                </div>
              </div>
              <div className="flex justify-end gap-3">
                <button
                  onClick={() => setShowSandboxModal(false)}
                  className="px-4 py-2 rounded-lg hover:bg-secondary transition-colors"
                >
                  Close
                </button>
                <button
                  className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 disabled:opacity-50 flex items-center gap-2"
                  onClick={openPreview}
                  disabled={openingPreview}
                >
                  {openingPreview ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Opening...
                    </>
                  ) : (
                    "Open Preview"
                  )}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderEvaluationTab = () => {
    const rubricMeta = evalData?.rubric_metadata;
    const categories = evalData?.evaluation_categories || [];

    return (
      <div id="eval-content" className="space-y-6">
        <div id="eval-header-section" className="border-b border-border pb-4">
          <div className="flex items-center justify-between mb-4">
            <div className="flex-1">
              <input
                id="eval-title-input"
                type="text"
                value={rubricMeta?.task_title || ""}
                onChange={(e) => updateEvalMetadata("task_title", e.target.value)}
                placeholder="Evaluation Title"
                className="text-xl font-bold bg-transparent border-none w-full focus:outline-none focus:ring-2 focus:ring-primary/20 rounded px-2"
              />
              <input
                id="eval-seniority-input"
                type="text"
                value={rubricMeta?.role_seniority || ""}
                onChange={(e) => updateEvalMetadata("role_seniority", e.target.value)}
                placeholder="Role Seniority"
                className="text-xs text-muted-foreground bg-transparent border border-border rounded px-2 py-1 mt-2 focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </div>
            <div className="flex items-center gap-3">
              <div className="text-center px-4 py-2 bg-secondary rounded-lg">
                <p className="text-xs text-muted-foreground">TOTAL</p>
                <input
                  id="eval-total-points-input"
                  type="number"
                  value={rubricMeta?.total_possible_points || 100}
                  onChange={(e) => updateEvalMetadata("total_possible_points", parseInt(e.target.value) || 100)}
                  className="text-lg font-bold bg-transparent border-none w-16 text-center focus:outline-none focus:ring-2 focus:ring-primary/20 rounded"
                />
              </div>
              <div className="text-center px-4 py-2 bg-green-100 dark:bg-green-900/30 rounded-lg">
                <p className="text-xs text-muted-foreground">PASS %</p>
                <input
                  id="eval-pass-threshold-input"
                  type="number"
                  value={rubricMeta?.passing_threshold_percentage || 70}
                  onChange={(e) => updateEvalMetadata("passing_threshold_percentage", parseInt(e.target.value) || 70)}
                  className="text-lg font-bold text-green-700 dark:text-green-400 bg-transparent border-none w-16 text-center focus:outline-none focus:ring-2 focus:ring-primary/20 rounded"
                />
              </div>
            </div>
          </div>
        </div>

        <div id="eval-categories" className="space-y-4">
          {categories.map((category, catIdx) => {
            const isExpanded = expandedCategories.has(category.category_name);
            const totalCatPoints = category.criteria?.reduce((sum, c) => sum + (c.max_points || 0), 0) || 0;

            return (
              <div key={catIdx} id={`category-${catIdx}`} className="border border-border rounded-xl overflow-hidden">
                <div className="flex items-center justify-between p-4 hover:bg-secondary/50 transition-colors">
                  <div className="flex items-center gap-3 flex-1">
                    <input
                      id={`category-name-${catIdx}`}
                      type="text"
                      value={category.category_name}
                      onChange={(e) => updateEvalCategory(catIdx, "category_name", e.target.value)}
                      placeholder="Category name"
                      className="font-semibold bg-transparent border border-border rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-primary/20"
                    />
                    <input
                      id={`category-weight-${catIdx}`}
                      type="number"
                      value={category.category_weight_percentage || 0}
                      onChange={(e) => updateEvalCategory(catIdx, "category_weight_percentage", parseInt(e.target.value) || 0)}
                      className="w-16 text-xs px-2 py-1 rounded bg-primary/10 text-primary font-medium border border-border focus:outline-none focus:ring-2 focus:ring-primary/20"
                    />
                    <span className="text-xs text-muted-foreground">% • {totalCatPoints} pts</span>
                  </div>
                  <button
                    id={`category-toggle-${catIdx}`}
                    onClick={() => toggleCategory(category.category_name)}
                    className="p-1 hover:bg-secondary rounded"
                  >
                    <ChevronRight className={`w-4 h-4 transition-transform ${isExpanded ? "rotate-90" : ""}`} />
                  </button>
                </div>

                {isExpanded && (
                  <div id={`category-content-${catIdx}`} className="border-t border-border p-4 bg-secondary/20">
                    <textarea
                      id={`category-desc-${catIdx}`}
                      value={category.category_description || ""}
                      onChange={(e) => updateEvalCategory(catIdx, "category_description", e.target.value)}
                      placeholder="Category description"
                      className="text-sm text-muted-foreground mb-4 w-full bg-transparent border border-border rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-primary/20 min-h-[60px] resize-y"
                    />

                    <div className="space-y-3">
                      {(category.criteria || []).map((criterion, critIdx) => {
                        const isCritExpanded = expandedCriteria.has(criterion.criterion_id);

                        return (
                          <div key={critIdx} id={`criterion-${criterion.criterion_id}`} className="bg-card rounded-lg border border-border overflow-hidden">
                            <div className="flex items-center justify-between p-3">
                              <div className="flex items-center gap-3 flex-1">
                                <input
                                  id={`criterion-name-${catIdx}-${critIdx}`}
                                  type="text"
                                  value={criterion.criterion_name}
                                  onChange={(e) => updateEvalCriterion(catIdx, critIdx, "criterion_name", e.target.value)}
                                  placeholder="Criterion name"
                                  className="text-sm font-medium bg-transparent border border-border rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-primary/20"
                                />
                                <input
                                  id={`criterion-points-${catIdx}-${critIdx}`}
                                  type="number"
                                  value={criterion.max_points || 0}
                                  onChange={(e) => updateEvalCriterion(catIdx, critIdx, "max_points", parseInt(e.target.value) || 0)}
                                  className="w-16 text-xs px-2 py-0.5 rounded bg-secondary border border-border focus:outline-none focus:ring-2 focus:ring-primary/20"
                                />
                                <span className="text-xs text-muted-foreground">pts</span>
                              </div>
                              <button
                                id={`criterion-toggle-${criterion.criterion_id}`}
                                onClick={() => toggleCriterion(criterion.criterion_id)}
                                className="p-1 hover:bg-secondary rounded"
                              >
                                <ChevronRight className={`w-4 h-4 transition-transform ${isCritExpanded ? "rotate-90" : ""}`} />
                              </button>
                            </div>

                            {isCritExpanded && (
                              <div id={`criterion-content-${criterion.criterion_id}`} className="border-t border-border p-4 bg-secondary/10">
                                <textarea
                                  id={`criterion-desc-${catIdx}-${critIdx}`}
                                  value={criterion.criterion_description || ""}
                                  onChange={(e) => updateEvalCriterion(catIdx, critIdx, "criterion_description", e.target.value)}
                                  placeholder="Criterion description"
                                  className="text-sm mb-4 w-full bg-transparent border border-border rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-primary/20 min-h-[60px] resize-y"
                                />

                                <div className="space-y-3">
                                  {Object.entries(criterion.scoring_rubric || {}).map(([level, rubric]) => (
                                    <div key={level} className={`rounded-lg p-3 border ${
                                      level === "excellent" ? "border-green-200 bg-green-50/50 dark:border-green-800 dark:bg-green-900/10" :
                                      level === "good" ? "border-blue-200 bg-blue-50/50 dark:border-blue-800 dark:bg-blue-900/10" :
                                      level === "adequate" ? "border-amber-200 bg-amber-50/50 dark:border-amber-800 dark:bg-amber-900/10" :
                                      "border-red-200 bg-red-50/50 dark:border-red-800 dark:bg-red-900/10"
                                    }`}>
                                      <div className="flex items-center justify-between mb-2">
                                        <span className={`text-xs font-semibold uppercase ${
                                          level === "excellent" ? "text-green-700 dark:text-green-400" :
                                          level === "good" ? "text-blue-700 dark:text-blue-400" :
                                          level === "adequate" ? "text-amber-700 dark:text-amber-400" :
                                          "text-red-700 dark:text-red-400"
                                        }`}>{level}</span>
                                        <input
                                          id={`rubric-range-${catIdx}-${critIdx}-${level}`}
                                          type="text"
                                          value={rubric.point_range || ""}
                                          onChange={(e) => updateScoringRubric(catIdx, critIdx, level, "point_range", e.target.value)}
                                          placeholder="e.g. 8-10"
                                          className="text-xs font-mono w-16 bg-transparent border border-border rounded px-1 py-0.5 focus:outline-none focus:ring-2 focus:ring-primary/20"
                                        />
                                      </div>
                                      <textarea
                                        id={`rubric-desc-${catIdx}-${critIdx}-${level}`}
                                        value={rubric.description || ""}
                                        onChange={(e) => updateScoringRubric(catIdx, critIdx, level, "description", e.target.value)}
                                        placeholder="Description"
                                        className="text-xs w-full bg-transparent border border-border rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-primary/20 min-h-[40px] resize-y"
                                      />
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div id="eval-calibration" className="bg-secondary/30 rounded-xl p-4">
          <h3 className="font-semibold mb-2">Calibration Notes</h3>
          <textarea
            id="eval-calibration-input"
            value={rubricMeta?.calibration_notes || ""}
            onChange={(e) => updateEvalMetadata("calibration_notes", e.target.value)}
            placeholder="Calibration notes..."
            className="text-sm text-muted-foreground w-full bg-transparent border border-border rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-primary/20 min-h-[60px] resize-y"
          />
        </div>
      </div>
    );
  };

  return (
    <div id="assessment-round-editor" className="bg-card rounded-2xl border border-amber-200 dark:border-amber-800 transition-all duration-200">
      <div id="assessment-header" className="flex items-center justify-between p-6 border-b border-amber-200 dark:border-amber-800/50">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
            <ClipboardList className="w-6 h-6 text-amber-600 dark:text-amber-400" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 id="assessment-heading" className="text-2xl font-bold">
                {taskData?.scenario?.title || round.name}
              </h1>
              <span className="text-xs px-2 py-1 rounded-full bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400">
                Assessment
              </span>
            </div>
            <p className="text-muted-foreground text-sm mt-1">Round {round.round_number}</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <span id="assessment-duration" className="text-sm text-muted-foreground flex items-center gap-2">
            <Clock className="w-4 h-4" />
            {taskData?.task_metadata?.estimated_time || template?.time_limit_minutes || round.duration_minutes} mins
          </span>
          {taskData?.task_metadata?.skills_tested && (
            <div className="flex gap-1">
              {taskData.task_metadata.skills_tested.slice(0, 3).map((skill, idx) => (
                <span key={idx} className="text-xs px-2 py-1 rounded-full bg-secondary truncate max-w-[100px]" title={skill.skill_name}>
                  {skill.skill_name.split(" ")[0]}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      <div id="assessment-tabs" className="border-b border-amber-200 dark:border-amber-800/50">
        <div className="flex">
          <button
            id="task-tab"
            onClick={() => setActiveTab("task")}
            className={`flex-1 px-6 py-4 text-sm font-medium transition-colors relative ${
              activeTab === "task"
                ? "text-amber-700 dark:text-amber-400"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            Tasks
            {activeTab === "task" && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-amber-500" />
            )}
          </button>
          <button
            id="evaluation-tab"
            onClick={() => setActiveTab("evaluation")}
            className={`flex-1 px-6 py-4 text-sm font-medium transition-colors relative ${
              activeTab === "evaluation"
                ? "text-amber-700 dark:text-amber-400"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            Evaluation Framework
            {activeTab === "evaluation" && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-amber-500" />
            )}
          </button>
        </div>
      </div>

      <div id="assessment-content" className="p-8 overflow-y-auto">
        {activeTab === "task" ? renderTaskTab() : renderEvaluationTab()}
      </div>

      <div id="assessment-actions" className="flex justify-between p-6 border-t border-amber-200 dark:border-amber-800/50">
        <button
          id="save-assessment-round-btn"
          onClick={handleSave}
          disabled={savingRoundId === round.id || savingTemplate}
          className="flex items-center gap-2 px-6 py-3 border border-border rounded-lg hover:bg-secondary transition-all duration-200 disabled:opacity-50"
        >
          {savingRoundId === round.id || savingTemplate ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Save className="w-4 h-4" />
          )}
          {savingRoundId === round.id || savingTemplate ? "Saving..." : "Save Assessment"}
        </button>
        {!isLastRound ? (
          <button
            id="next-assessment-round-btn"
            onClick={async () => {
              await handleSave();
              onNextRound();
            }}
            className="flex items-center gap-2 px-8 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
          >
            Next Round
            <ChevronRight className="w-4 h-4" />
          </button>
        ) : (
          <button
            id="save-all-assessment-btn"
            onClick={handleSaveAll}
            disabled={savingAll || savingTemplate}
            className="flex items-center gap-2 px-8 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-all duration-200 disabled:opacity-50"
          >
            {(savingAll || savingTemplate) && <Loader2 className="w-4 h-4 animate-spin" />}
            {savingAll || savingTemplate ? "Saving..." : "Save All Changes"}
          </button>
        )}
      </div>
    </div>
  );
}

interface SortableRoundItemProps {
  round: Round;
  index: number;
  isSelected: boolean;
  isDeleting: boolean;
  onSelect: () => void;
  onDelete: () => void;
}

function SortableRoundItem({ round, index, isSelected, isDeleting, onSelect, onDelete }: SortableRoundItemProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: round.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      id={`sidebar-round-${round.id}`}
      className={`relative transition-all duration-200 ${isDeleting ? "opacity-50 scale-95" : ""}`}
    >
      <div
        id={`timeline-dot-${round.id}`}
        className={`absolute -left-8 top-1 w-6 h-6 rounded-full border-2 flex items-center justify-center bg-card transition-all duration-200 ${
          isSelected ? "border-primary scale-110" : "border-border"
        } ${round.round_type === "assessment" ? "border-amber-500" : ""}`}
      >
        {round.round_type === "assessment" ? (
          <ClipboardList className={`w-3 h-3 ${isSelected ? "text-amber-500" : "text-muted-foreground"}`} />
        ) : (
          isSelected && <div className="w-2 h-2 rounded-full bg-primary" />
        )}
      </div>

      <div id={`round-info-${round.id}`} className="flex items-start justify-between gap-2">
        <div
          {...attributes}
          {...listeners}
          className="cursor-grab active:cursor-grabbing p-1 -ml-1 text-muted-foreground hover:text-foreground"
        >
          <GripVertical className="w-4 h-4" />
        </div>
        <div className="flex-1 cursor-pointer" onClick={onSelect}>
          <div className="flex items-center gap-2">
            <p
              id={`round-label-${round.id}`}
              className={`text-xs transition-colors ${isSelected ? "text-foreground font-medium" : "text-muted-foreground"}`}
            >
              Round {round.round_number}
            </p>
            {round.round_type === "assessment" ? (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400">
                Assessment
              </span>
            ) : (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400">
                Interview
              </span>
            )}
          </div>
          <p
            id={`round-name-${round.id}`}
            className={`text-sm font-semibold transition-colors ${isSelected ? "text-foreground" : "text-muted-foreground"}`}
          >
            {round.name}
          </p>
          <p className="text-xs text-muted-foreground">{round.duration_minutes} mins</p>
        </div>
        <button
          id={`delete-round-btn-${round.id}`}
          type="button"
          disabled={isDeleting}
          className="p-1 text-destructive hover:bg-destructive/10 rounded transition-colors disabled:opacity-50"
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          title="Delete round"
        >
          {isDeleting ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <Trash2 className="w-3 h-3" />
          )}
        </button>
      </div>
    </div>
  );
}

export default function PlanEditPage() {
  const params = useParams();
  const router = useRouter();
  const reqId = params.id as string;

  const [requisition, setRequisition] = useState<Requisition | null>(null);
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [plan, setPlan] = useState<InterviewPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const [selectedRoundIndex, setSelectedRoundIndex] = useState(0);
  const [editingQuestionId, setEditingQuestionId] = useState<string | null>(null);
  const [showDetailsPopup, setShowDetailsPopup] = useState(false);
  const [showGuidelinesPopup, setShowGuidelinesPopup] = useState(false);
  const [newSkill, setNewSkill] = useState("");
  const [newGuidelineTitle, setNewGuidelineTitle] = useState("");
  const [newGuidelineDesc, setNewGuidelineDesc] = useState("");

  // Granular loading states
  const [savingRoundId, setSavingRoundId] = useState<string | null>(null);
  const [savingQuestionId, setSavingQuestionId] = useState<string | null>(null);
  const [addingRound, setAddingRound] = useState(false);
  const [addingQuestionToRound, setAddingQuestionToRound] = useState<string | null>(null);
  const [deletingRoundId, setDeletingRoundId] = useState<string | null>(null);
  const [deletingQuestionId, setDeletingQuestionId] = useState<string | null>(null);
  const [savingAll, setSavingAll] = useState(false);
  const [updatingStatus, setUpdatingStatus] = useState(false);
  const [reorderingRounds, setReorderingRounds] = useState(false);

  // Add Round Modal states
  const [showAddRoundModal, setShowAddRoundModal] = useState(false);
  const [addRoundStep, setAddRoundStep] = useState<"type" | "assessment-source" | "assessment-form">("type");
  const [selectedRoundType, setSelectedRoundType] = useState<"interview" | "assessment" | null>(null);
  const [assessmentSource, setAssessmentSource] = useState<"library" | "new" | null>(null);
  const [assessmentTemplates, setAssessmentTemplates] = useState<AssessmentTemplate[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);

  // New assessment form states
  const [taskDefinitionJson, setTaskDefinitionJson] = useState("");
  const [evalRubricJson, setEvalRubricJson] = useState("");
  const [taskJsonError, setTaskJsonError] = useState<string | null>(null);
  const [evalJsonError, setEvalJsonError] = useState<string | null>(null);
  const [newAssessmentTools, setNewAssessmentTools] = useState<string[]>(["excalidraw", "voice_recorder"]);

  const toggleNewAssessmentTool = (toolId: string) => {
    setNewAssessmentTools((prev) =>
      prev.includes(toolId) ? prev.filter((t) => t !== toolId) : [...prev, toolId]
    );
  };

  const inferFromTaskJson = (taskJson: string, evalJson?: string) => {
    const defaults = {
      title: "",
      description: "",
      duration: 60,
      tools: ["excalidraw", "voice_recorder"],
      role_seniority: "",
    };
    try {
      const task = JSON.parse(taskJson);
      defaults.title = task?.scenario?.title || task?.display?.title || task?.context?.scenario_title || "";
      defaults.description = task?.scenario?.challenge_statement || task?.task_requirements?.primary_objective || task?.display?.description || task?.context?.challenge_statement || "";
      defaults.role_seniority = task?.task_metadata?.seniority_level || task?.display?.role_seniority || task?.context?.role_position || "";
      defaults.duration = task?.task_metadata?.estimated_time || task?.metadata?.estimated_time_minutes || 60;
      defaults.tools = task?.metadata?.tools_enabled || ["excalidraw", "voice_recorder"];
    } catch {
      // ignore parse errors
    }
    if (evalJson) {
      try {
        const evalData = JSON.parse(evalJson);
        if (!defaults.title && evalData?.rubric_metadata?.task_title) {
          defaults.title = evalData.rubric_metadata.task_title;
        }
        if (!defaults.role_seniority && evalData?.rubric_metadata?.role_seniority) {
          defaults.role_seniority = evalData.rubric_metadata.role_seniority;
        }
      } catch {
        // ignore parse errors
      }
    }
    return defaults;
  };

  const API_URL = getRuntimeConfig().apiUrl || "http://localhost:8004";

  // V2 backend base — admin endpoints ported to /api/v2/admin.

  const API_V2_URL = getRuntimeConfig().apiV2Url || "http://localhost:8004";

  useEffect(() => {
    fetchData();
  }, [reqId]);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);

      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        router.push("/login");
        return;
      }

      const headers = {
        "Authorization": `Bearer ${session.access_token}`,
        "Content-Type": "application/json",
      };

      const [reqResponse, planResponse] = await Promise.all([
        fetch(`${API_V2_URL}/api/v2/admin/requisitions/${reqId}`, { headers }),
        fetch(`${API_V2_URL}/api/v2/admin/requisitions/${reqId}/plan`, { headers }),
      ]);

      if (!reqResponse.ok) {
        throw new Error("Failed to fetch requisition");
      }
      const reqData = await reqResponse.json();
      setRequisition(reqData);

      if (planResponse.ok) {
        const planData = await planResponse.json();
        const normalizedPlan = {
          ...planData,
          rounds: planData.rounds.map((r: Round) => ({
            ...r,
            round_type: r.round_type || (r.assessment_template_id ? "assessment" : "interview"),
          })),
        };
        setPlan(normalizedPlan);
      } else {
        router.push(`/requisitions/${reqId}/plan`);
        return;
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

  const getAuthHeaders = async () => {
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

  const fetchAssessmentTemplates = useCallback(async () => {
    try {
      setLoadingTemplates(true);
      const headers = await getAuthHeaders();
      if (!headers) return;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/assessment-templates?status=published`, { headers });
      if (response.ok) {
        const data = await response.json();
        setAssessmentTemplates(data.templates || []);
      }
    } catch (err) {
      console.error("Error fetching assessment templates:", err);
    } finally {
      setLoadingTemplates(false);
    }
  }, [API_URL]);

  const handleLogout = () => {
    localStorage.removeItem("admin_auth");
    router.push("/login");
  };

  const showSuccess = (message: string) => {
    setSuccessMessage(message);
    setTimeout(() => setSuccessMessage(null), 3000);
  };

  const showError = (message: string) => {
    setError(message);
    setTimeout(() => setError(null), 5000);
  };

  const updateLocalRound = (roundId: string, updates: Partial<Round>) => {
    if (!plan) return;
    setPlan({
      ...plan,
      rounds: plan.rounds.map((r) => (r.id === roundId ? { ...r, ...updates } : r)),
    });
  };

  const updateLocalQuestion = (roundId: string, questionId: string, updates: Partial<FeedbackQuestion>) => {
    if (!plan) return;
    setPlan({
      ...plan,
      rounds: plan.rounds.map((r) =>
        r.id === roundId
          ? {
              ...r,
              feedback_questions: (r.feedback_questions || []).map((q) =>
                q.id === questionId ? { ...q, ...updates } : q
              ),
            }
          : r
      ),
    });
  };

  const formatDuration = (minutes: number): string => {
    if (minutes < 60) return `${minutes} mins`;
    const hours = Math.floor(minutes / 60);
    const remaining = minutes % 60;
    if (remaining === 0) return hours === 1 ? "1 hr" : `${hours} hrs`;
    return hours === 1 ? `1 hr ${remaining} mins` : `${hours} hrs ${remaining} mins`;
  };

  const recalculatePlanTotals = (rounds: Round[]): Partial<InterviewPlan> => {
    const totalDuration = rounds.reduce((sum, r) => sum + r.duration_minutes, 0);
    return {
      total_rounds: rounds.length,
      total_duration_minutes: totalDuration,
      total_duration_display: formatDuration(totalDuration),
    };
  };

  const saveRound = async (round: Round) => {
    try {
      setSavingRoundId(round.id);
      const headers = await getAuthHeaders();
      if (!headers) return;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/requisitions/rounds/${round.id}`, {
        method: "PUT",
        headers,
        body: JSON.stringify({
          name: round.name,
          category: round.category,
          duration_minutes: round.duration_minutes,
          description: round.description,
          skills: round.skills,
        }),
      });

      if (!response.ok) throw new Error("Failed to save round");
      showSuccess("Round saved");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSavingRoundId(null);
    }
  };

  const saveQuestion = async (question: FeedbackQuestion) => {
    try {
      setSavingQuestionId(question.id);
      const headers = await getAuthHeaders();
      if (!headers) return;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/requisitions/questions/${question.id}`, {
        method: "PUT",
        headers,
        body: JSON.stringify({
          heading: question.heading,
          description: question.description || null,
        }),
      });

      if (!response.ok) throw new Error("Failed to save question");
      showSuccess("Question saved");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSavingQuestionId(null);
    }
  };

  const openAddRoundModal = () => {
    setShowAddRoundModal(true);
    setAddRoundStep("type");
    setSelectedRoundType(null);
    setAssessmentSource(null);
    setSelectedTemplateId(null);
    setTaskDefinitionJson("");
    setEvalRubricJson("");
    setTaskJsonError(null);
    setEvalJsonError(null);
  };

  const closeAddRoundModal = () => {
    setShowAddRoundModal(false);
    setAddRoundStep("type");
    setSelectedRoundType(null);
    setAssessmentSource(null);
  };

  const handleRoundTypeSelect = (type: "interview" | "assessment") => {
    setSelectedRoundType(type);
    if (type === "interview") {
      addInterviewRound();
      closeAddRoundModal();
    } else {
      fetchAssessmentTemplates();
      setAddRoundStep("assessment-source");
    }
  };

  const handleAssessmentSourceSelect = (source: "library" | "new") => {
    setAssessmentSource(source);
    if (source === "new") {
      setAddRoundStep("assessment-form");
    }
  };

  const handleSelectTemplate = (templateId: string) => {
    setSelectedTemplateId(templateId);
  };

  const addInterviewRound = async () => {
    if (!plan) return;
    try {
      setAddingRound(true);
      const headers = await getAuthHeaders();
      if (!headers) return;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/requisitions/${reqId}/rounds`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          name: "New Round",
          category: "coding",
          duration_minutes: 45,
          description: "A new interview round.",
          skills: ["Technical Skills"],
          round_type: "interview",
        }),
      });

      if (!response.ok) throw new Error("Failed to add round");
      const newRound = await response.json();

      const questionResponse = await fetch(`${API_V2_URL}/api/v2/admin/requisitions/rounds/${newRound.id}/questions`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          heading: "Rate candidate's technical skills",
        }),
      });

      let newQuestion = null;
      if (questionResponse.ok) {
        newQuestion = await questionResponse.json();
      }

      const roundWithQuestion: Round = {
        ...newRound,
        round_type: "interview",
        guidelines: newRound.guidelines || [],
        feedback_questions: newQuestion ? [{ ...newQuestion, heading: newQuestion.heading }] : [],
      };

      const newRounds = [...plan.rounds, roundWithQuestion];
      setPlan({
        ...plan,
        ...recalculatePlanTotals(newRounds),
        rounds: newRounds,
      });

      setSelectedRoundIndex(newRounds.length - 1);
      showSuccess("Interview round added");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to add round");
    } finally {
      setAddingRound(false);
    }
  };

  const validateJson = (jsonString: string, type: "task" | "eval"): boolean => {
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

  const addAssessmentRoundFromLibrary = async () => {
    if (!plan || !selectedTemplateId) return;
    const template = assessmentTemplates.find(t => t.id === selectedTemplateId);
    if (!template) return;

    try {
      setAddingRound(true);
      const headers = await getAuthHeaders();
      if (!headers) return;

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
      const newRound = await response.json();

      const roundWithTemplate: Round = {
        ...newRound,
        round_type: "assessment",
        assessment_template_id: template.id,
        assessment_template: template,
        guidelines: [],
        feedback_questions: [],
      };

      const newRounds = [...plan.rounds, roundWithTemplate];
      setPlan({
        ...plan,
        ...recalculatePlanTotals(newRounds),
        rounds: newRounds,
      });

      setSelectedRoundIndex(newRounds.length - 1);
      closeAddRoundModal();
      showSuccess("Assessment round added from library");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to add assessment round");
    } finally {
      setAddingRound(false);
    }
  };

  const addNewAssessmentRound = async () => {
    if (!plan) return;

    const taskValid = validateJson(taskDefinitionJson, "task");
    const evalValid = validateJson(evalRubricJson, "eval");
    if (!taskValid || !evalValid) return;

    const inferred = inferFromTaskJson(taskDefinitionJson, evalRubricJson);
    if (!inferred.title.trim()) {
      showError("Task definition must include scenario.title or display.title");
      return;
    }

    try {
      setAddingRound(true);
      const headers = await getAuthHeaders();
      if (!headers) return;

      const templateResponse = await fetch(`${API_V2_URL}/api/v2/admin/assessment-templates`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          title: inferred.title,
          description: inferred.description || null,
          role_seniority: inferred.role_seniority || null,
          time_limit_minutes: inferred.duration,
          tools_enabled: newAssessmentTools,
          task_definition: JSON.parse(taskDefinitionJson),
          evaluation_rubric: JSON.parse(evalRubricJson),
          status: "published",
        }),
      });

      if (!templateResponse.ok) throw new Error("Failed to create assessment template");
      const newTemplate = await templateResponse.json();

      const response = await fetch(`${API_V2_URL}/api/v2/admin/requisitions/${reqId}/rounds`, {
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

      if (!response.ok) throw new Error("Failed to add assessment round");
      const newRound = await response.json();

      const roundWithTemplate: Round = {
        ...newRound,
        round_type: "assessment",
        assessment_template_id: newTemplate.id,
        assessment_template: newTemplate,
        guidelines: [],
        feedback_questions: [],
      };

      const newRounds = [...plan.rounds, roundWithTemplate];
      setPlan({
        ...plan,
        ...recalculatePlanTotals(newRounds),
        rounds: newRounds,
      });

      setSelectedRoundIndex(newRounds.length - 1);
      closeAddRoundModal();
      showSuccess("New assessment round created and added");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to create assessment");
    } finally {
      setAddingRound(false);
    }
  };

  const deleteRound = async (roundId: string) => {
    if (!plan || plan.rounds.length <= 1) return;
    try {
      setDeletingRoundId(roundId);
      const headers = await getAuthHeaders();
      if (!headers) return;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/requisitions/rounds/${roundId}`, {
        method: "DELETE",
        headers,
      });

      if (!response.ok) throw new Error("Failed to delete round");

      const deletedIndex = plan.rounds.findIndex(r => r.id === roundId);
      const newRounds = plan.rounds.filter((r) => r.id !== roundId);

      setPlan({
        ...plan,
        ...recalculatePlanTotals(newRounds),
        rounds: newRounds,
      });

      if (selectedRoundIndex >= newRounds.length) {
        setSelectedRoundIndex(Math.max(0, newRounds.length - 1));
      } else if (selectedRoundIndex > deletedIndex) {
        setSelectedRoundIndex(selectedRoundIndex - 1);
      }

      showSuccess("Round deleted");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to delete round");
    } finally {
      setDeletingRoundId(null);
    }
  };

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id || !plan) return;

    const oldIndex = plan.rounds.findIndex(r => r.id === active.id);
    const newIndex = plan.rounds.findIndex(r => r.id === over.id);

    if (oldIndex === -1 || newIndex === -1) return;

    const previousRounds = [...plan.rounds];
    const previousSelectedIndex = selectedRoundIndex;

    const newRounds = arrayMove(plan.rounds, oldIndex, newIndex);

    const updatedRounds = newRounds.map((r, idx) => ({
      ...r,
      round_number: idx + 1,
    }));

    setPlan({
      ...plan,
      rounds: updatedRounds,
    });

    let newSelectedIndex = selectedRoundIndex;
    if (selectedRoundIndex === oldIndex) {
      newSelectedIndex = newIndex;
    } else if (oldIndex < selectedRoundIndex && newIndex >= selectedRoundIndex) {
      newSelectedIndex = selectedRoundIndex - 1;
    } else if (oldIndex > selectedRoundIndex && newIndex <= selectedRoundIndex) {
      newSelectedIndex = selectedRoundIndex + 1;
    }
    setSelectedRoundIndex(newSelectedIndex);

    try {
      setReorderingRounds(true);
      const headers = await getAuthHeaders();
      if (!headers) {
        setPlan({ ...plan, rounds: previousRounds });
        setSelectedRoundIndex(previousSelectedIndex);
        return;
      }

      const roundOrders = updatedRounds.map((r) => ({
        round_id: r.id,
        round_number: r.round_number,
      }));

      const response = await fetch(`${API_V2_URL}/api/v2/admin/requisitions/${reqId}/rounds/reorder`, {
        method: "PUT",
        headers,
        body: JSON.stringify({ round_orders: roundOrders }),
      });

      if (!response.ok) {
        setPlan({ ...plan, rounds: previousRounds });
        setSelectedRoundIndex(previousSelectedIndex);
        throw new Error("Failed to save reorder");
      }
      showSuccess("Rounds reordered");
    } catch (err) {
      setPlan({ ...plan, rounds: previousRounds });
      setSelectedRoundIndex(previousSelectedIndex);
      showError(err instanceof Error ? err.message : "Failed to save reorder");
    } finally {
      setReorderingRounds(false);
    }
  };

  const addQuestion = async (roundId: string) => {
    if (!plan) return;
    const round = plan.rounds.find((r) => r.id === roundId);
    if (!round) return;

    try {
      setAddingQuestionToRound(roundId);
      const headers = await getAuthHeaders();
      if (!headers) return;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/requisitions/rounds/${roundId}/questions`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          heading: "New evaluation criterion",
        }),
      });

      if (!response.ok) throw new Error("Failed to add question");
      const newQuestion = await response.json();

      const questionWithText = {
        ...newQuestion,
        heading: newQuestion.heading || newQuestion.heading,
      };

      setPlan({
        ...plan,
        rounds: plan.rounds.map((r) =>
          r.id === roundId
            ? { ...r, feedback_questions: [...(r.feedback_questions || []), questionWithText] }
            : r
        ),
      });

      showSuccess("Question added");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to add question");
    } finally {
      setAddingQuestionToRound(null);
    }
  };

  const deleteQuestion = async (roundId: string, questionId: string) => {
    if (!plan) return;
    try {
      setDeletingQuestionId(questionId);
      const headers = await getAuthHeaders();
      if (!headers) return;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/requisitions/questions/${questionId}`, {
        method: "DELETE",
        headers,
      });

      if (!response.ok) throw new Error("Failed to delete question");

      setPlan({
        ...plan,
        rounds: plan.rounds.map((r) =>
          r.id === roundId
            ? { ...r, feedback_questions: (r.feedback_questions || []).filter((q) => q.id !== questionId) }
            : r
        ),
      });

      showSuccess("Question deleted");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to delete question");
    } finally {
      setDeletingQuestionId(null);
    }
  };

  const handleRoundNameChange = (roundId: string, name: string) => {
    updateLocalRound(roundId, { name });
  };

  const handleRoundDescriptionChange = (roundId: string, description: string) => {
    updateLocalRound(roundId, { description });
  };

  const handleRoundDurationChange = (roundId: string, duration: number) => {
    if (!plan) return;
    const newRounds = plan.rounds.map((r) =>
      r.id === roundId ? { ...r, duration_minutes: duration, duration_display: formatDuration(duration) } : r
    );
    setPlan({
      ...plan,
      ...recalculatePlanTotals(newRounds),
      rounds: newRounds,
    });
  };

  const handleQuestionTextChange = (roundId: string, questionId: string, text: string) => {
    updateLocalQuestion(roundId, questionId, { heading: text });
  };

  const handleQuestionDescriptionChange = (roundId: string, questionId: string, description: string) => {
    updateLocalQuestion(roundId, questionId, { description });
  };

  const addSkill = (roundId: string) => {
    if (!newSkill.trim() || !plan) return;
    const round = plan.rounds.find((r) => r.id === roundId);
    if (!round) return;
    updateLocalRound(roundId, { skills: [...round.skills, newSkill.trim()] });
    setNewSkill("");
  };

  const removeSkill = (roundId: string, skillIndex: number) => {
    if (!plan) return;
    const round = plan.rounds.find((r) => r.id === roundId);
    if (!round) return;
    updateLocalRound(roundId, { skills: round.skills.filter((_, i) => i !== skillIndex) });
  };

  const addGuideline = (roundId: string) => {
    if (!newGuidelineTitle.trim() || !plan) return;
    const round = plan.rounds.find((r) => r.id === roundId);
    if (!round) return;
    updateLocalRound(roundId, {
      guidelines: [...(round.guidelines || []), { title: newGuidelineTitle.trim(), description: newGuidelineDesc.trim() }],
    });
    setNewGuidelineTitle("");
    setNewGuidelineDesc("");
  };

  const removeGuideline = (roundId: string, guidelineIndex: number) => {
    if (!plan) return;
    const round = plan.rounds.find((r) => r.id === roundId);
    if (!round) return;
    updateLocalRound(roundId, { guidelines: (round.guidelines || []).filter((_, i) => i !== guidelineIndex) });
  };

  const updateGuideline = (roundId: string, index: number, field: "title" | "description", value: string) => {
    if (!plan) return;
    const round = plan.rounds.find((r) => r.id === roundId);
    if (!round) return;
    const newGuidelines = [...(round.guidelines || [])];
    newGuidelines[index] = { ...newGuidelines[index], [field]: value };
    updateLocalRound(roundId, { guidelines: newGuidelines });
  };

  const handleSaveAll = async () => {
    if (!plan) return;
    try {
      setSavingAll(true);
      setError(null);

      const headers = await getAuthHeaders();
      if (!headers) return;

      const planData = {
        rounds: plan.rounds.map((r) => ({
          round_number: r.round_number,
          name: r.name,
          category: r.category,
          duration_minutes: r.duration_minutes,
          description: r.description,
          skills: r.skills,
          guidelines: r.guidelines || [],
          round_type: r.round_type || "interview",
          assessment_template_id: r.assessment_template_id || null,
          feedback_questions: r.round_type === "assessment" ? [] : (r.feedback_questions || []).map((q) => ({
            heading: q.heading,
            description: q.description || null,
          })),
        })),
      };

      const response = await fetch(`${API_V2_URL}/api/v2/admin/requisitions/${reqId}/plan`, {
        method: "PUT",
        headers,
        body: JSON.stringify(planData),
      });

      if (!response.ok) throw new Error("Failed to save plan");

      await fetchData();

      showSuccess("All changes saved successfully");
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSavingAll(false);
    }
  };

  const updateStatus = async (newStatus: string) => {
    try {
      setUpdatingStatus(true);
      const headers = await getAuthHeaders();
      if (!headers) return false;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/requisitions/${reqId}/status`, {
        method: "PUT",
        headers,
        body: JSON.stringify({ status: newStatus }),
      });

      if (!response.ok) throw new Error("Failed to update status");

      const updatedReq = await response.json();
      setRequisition(updatedReq);
      showSuccess(`Status changed to ${newStatus === 'planned' ? 'Planned' : 'Intake Pending'}`);
      return true;
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to update status");
      return false;
    } finally {
      setUpdatingStatus(false);
    }
  };

  const handleRevertToIntake = async () => {
    await updateStatus('intake_pending');
  };

  const handleFinish = async () => {
    await handleSaveAll();

    if (requisition?.status !== 'planned') {
      const statusUpdated = await updateStatus('planned');
      if (!statusUpdated) return;
    }

    if (organization) {
      router.push(`/customers/${organization.id}`);
    }
  };

  if (loading) {
    return (
      <div id="edit-loading" className="min-h-screen bg-secondary/30 flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    );
  }

  if (error && !plan) {
    return (
      <div id="edit-error" className="min-h-screen bg-secondary/30 flex items-center justify-center">
        <div className="text-center">
          <p className="text-destructive mb-4">{error}</p>
          <Link href="/customers" className="text-primary hover:underline">
            Back to customers
          </Link>
        </div>
      </div>
    );
  }

  if (!plan || !requisition) {
    return null;
  }

  const selectedRound = plan.rounds[selectedRoundIndex];

  return (
    <AuthGuard>
      <div id="plan-edit-page" className="h-screen flex flex-col">
        <nav id="edit-nav" className="bg-card border-b border-border">
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
                  id="edit-back-link"
                  className="flex items-center gap-2 px-4 py-2 rounded-lg hover:bg-secondary transition-colors text-sm"
                >
                  <ArrowLeft className="w-4 h-4" />
                  Back to {organization.name}
                </Link>
              )}
              <ThemeToggle />
              <button
                id="edit-logout-btn"
                onClick={handleLogout}
                className="flex items-center gap-2 px-4 py-2 text-destructive hover:bg-destructive/10 rounded-lg transition-colors"
              >
                <LogOut className="w-4 h-4" />
                Logout
              </button>
            </div>
          </div>
        </nav>

        {(successMessage || error) && (
          <div
            id="toast-message"
            className={`fixed top-20 right-6 z-50 px-4 py-3 rounded-lg shadow-lg transition-all duration-300 animate-in slide-in-from-right ${
              successMessage
                ? "bg-green-100 dark:bg-green-900/50 text-green-800 dark:text-green-200"
                : "bg-red-100 dark:bg-red-900/50 text-red-800 dark:text-red-200"
            }`}
          >
            <div className="flex items-center gap-2">
              {successMessage && <Check className="w-4 h-4" />}
              {successMessage || error}
            </div>
          </div>
        )}

        <div id="edit-main" className="flex-1 flex min-h-0">
          <aside id="rounds-sidebar" className="w-72 border-r border-border bg-card p-5 overflow-y-auto">
            <div id="sidebar-header" className="mb-6">
              <div id="role-info-box" className="p-5 border-2 border-border rounded-xl bg-secondary/30">
                <h2 id="role-title" className="text-lg font-bold mb-2">{requisition.role_title}</h2>
                {requisition.role_location && (
                  <div id="role-location" className="flex items-center gap-2 text-sm text-muted-foreground">
                    <MapPin className="w-4 h-4" />
                    <span>{requisition.role_location}</span>
                  </div>
                )}
                <div id="role-experience" className="flex items-center gap-2 text-sm text-muted-foreground mt-1">
                  <Briefcase className="w-4 h-4" />
                  <span>{requisition.experience_display}</span>
                </div>
                <div id="plan-summary" className="flex items-center gap-2 text-sm text-muted-foreground mt-2 pt-2 border-t border-border">
                  <Clock className="w-4 h-4" />
                  <span>{plan.total_rounds} rounds · {plan.total_duration_display}</span>
                </div>
                <div id="status-section" className="mt-3 pt-3 border-t border-border">
                  <div className="flex items-center justify-between">
                    <span className={`text-xs font-medium px-2 py-1 rounded-full ${
                      requisition.status === 'planned'
                        ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400'
                        : 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400'
                    }`}>
                      {requisition.status === 'planned' ? 'Published' : 'Draft'}
                    </span>
                    {requisition.status === 'planned' && (
                      <button
                        id="revert-status-btn"
                        onClick={handleRevertToIntake}
                        disabled={updatingStatus}
                        className="text-xs text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50 flex items-center gap-1"
                      >
                        {updatingStatus ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <ArrowLeft className="w-3 h-3" />
                        )}
                        Unpublish
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>

            <div id="rounds-timeline" className="relative pl-8 mt-6">
              <div id="timeline-line" className="absolute left-[13px] top-3 bottom-16 w-0.5 bg-border" />

              <DndContext
                sensors={sensors}
                collisionDetection={closestCenter}
                onDragEnd={handleDragEnd}
              >
                <SortableContext
                  items={plan.rounds.map(r => r.id)}
                  strategy={verticalListSortingStrategy}
                >
                  <div id="rounds-list" className="space-y-6">
                    {plan.rounds.map((round, index) => (
                      <SortableRoundItem
                        key={round.id}
                        round={round}
                        index={index}
                        isSelected={selectedRoundIndex === index}
                        isDeleting={deletingRoundId === round.id}
                        onSelect={() => setSelectedRoundIndex(index)}
                        onDelete={() => deleteRound(round.id)}
                      />
                    ))}
                  </div>
                </SortableContext>
              </DndContext>

              <button
                id="add-round-btn"
                onClick={openAddRoundModal}
                disabled={addingRound}
                className="mt-8 flex items-center gap-2 px-4 py-2 border border-border rounded-lg hover:bg-secondary transition-all duration-200 text-sm disabled:opacity-50"
              >
                {addingRound ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Plus className="w-4 h-4" />
                )}
                {addingRound ? "Adding..." : "Add Round"}
              </button>
            </div>
          </aside>

          <main id="builder-main" className="flex-1 bg-secondary/30 p-6 overflow-y-auto">
            {selectedRound && selectedRound.round_type === "assessment" ? (
              <AssessmentRoundEditor
                round={selectedRound}
                onSave={async () => saveRound(selectedRound)}
                onSaveAll={handleSaveAll}
                onNextRound={() => setSelectedRoundIndex(selectedRoundIndex + 1)}
                onRefresh={fetchData}
                savingRoundId={savingRoundId}
                savingAll={savingAll}
                isLastRound={selectedRoundIndex >= plan.rounds.length - 1}
                apiUrl={API_V2_URL}
              />
            ) : selectedRound && (
              <div id="round-editor" className="bg-card rounded-2xl border border-blue-200 dark:border-blue-800 p-8 transition-all duration-200">
                <div id="round-header" className="flex items-center justify-between mb-8">
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-xl bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
                      <Users className="w-6 h-6 text-blue-600 dark:text-blue-400" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h1 id="round-heading" className="text-2xl font-bold">
                          {selectedRound.name}
                        </h1>
                        <span className="text-xs px-2 py-1 rounded-full bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400">
                          Interview
                        </span>
                      </div>
                      <p className="text-muted-foreground text-sm mt-1">Round {selectedRound.round_number}</p>
                    </div>
                    <button
                      id="view-details-btn"
                      onClick={() => setShowDetailsPopup(true)}
                      className="px-4 py-2 border border-border rounded-lg hover:bg-secondary transition-colors text-sm"
                    >
                      Edit Details
                    </button>
                    <button
                      id="view-guidelines-btn"
                      onClick={() => setShowGuidelinesPopup(true)}
                      className="px-4 py-2 border border-border rounded-lg hover:bg-secondary transition-colors text-sm"
                    >
                      Guidelines ({(selectedRound.guidelines || []).length})
                    </button>
                  </div>
                  <span id="round-duration" className="text-sm text-muted-foreground flex items-center gap-2">
                    <Clock className="w-4 h-4" />
                    {selectedRound.duration_minutes} mins
                  </span>
                </div>

                <div id="scorecard-section" className="border-2 border-border rounded-2xl p-8">
                  <div id="scorecard-header" className="flex items-center justify-between mb-8">
                    <h2 id="scorecard-title" className="text-xl font-bold">Feedback Questions</h2>
                    <span className="text-sm text-muted-foreground">
                      {(selectedRound.feedback_questions || []).length} questions
                    </span>
                  </div>

                  <div id="questions-list" className="space-y-4">
                    {(selectedRound.feedback_questions || []).map((question, qIndex) => (
                      <div
                        key={question.id}
                        id={`question-${question.id}`}
                        className={`border border-border rounded-xl p-4 hover:border-primary/50 transition-all duration-200 ${
                          deletingQuestionId === question.id ? "opacity-50 scale-98" : ""
                        } ${savingQuestionId === question.id ? "border-primary/50 bg-primary/5" : ""}`}
                      >
                        <div id={`question-header-${question.id}`} className="flex items-start justify-between gap-4">
                          <div className="flex items-start gap-3 flex-1">
                            <span className="w-6 h-6 rounded-full bg-primary/10 text-primary flex items-center justify-center text-sm font-medium flex-shrink-0 mt-0.5">
                              {qIndex + 1}
                            </span>
                            {editingQuestionId === question.id ? (
                              <div className="flex-1 space-y-2">
                                <div className="flex items-center gap-2">
                                  <input
                                    id={`question-edit-input-${question.id}`}
                                    value={question.heading ?? ""}
                                    onChange={(e) =>
                                      handleQuestionTextChange(selectedRound.id, question.id, e.target.value)
                                    }
                                    placeholder="Heading"
                                    className="flex-1 px-3 py-2 border border-primary rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                                    autoFocus
                                  />
                                  {savingQuestionId === question.id && (
                                    <Loader2 className="w-4 h-4 animate-spin text-primary" />
                                  )}
                                </div>
                                <div className="flex items-center gap-2">
                                  <input
                                    id={`question-desc-input-${question.id}`}
                                    value={question.description ?? ""}
                                    onChange={(e) =>
                                      handleQuestionDescriptionChange(selectedRound.id, question.id, e.target.value)
                                    }
                                    placeholder="Description (optional)"
                                    className="flex-1 px-3 py-1.5 text-sm border border-border rounded-lg bg-background focus:outline-none focus:border-primary"
                                  />
                                  <button
                                    id={`save-question-btn-${question.id}`}
                                    onClick={() => {
                                      saveQuestion(question);
                                      setEditingQuestionId(null);
                                    }}
                                    className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90"
                                  >
                                    Save
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <div id={`question-text-${question.id}`} className="flex-1">
                                <p className="text-sm font-medium">{question.heading}</p>
                                {question.description && (
                                  <p className="text-xs text-muted-foreground mt-0.5">{question.description}</p>
                                )}
                              </div>
                            )}
                          </div>
                          <div className="flex items-center gap-1">
                            {savingQuestionId === question.id && editingQuestionId !== question.id && (
                              <Loader2 className="w-4 h-4 animate-spin text-primary mr-1" />
                            )}
                            <button
                              id={`edit-question-btn-${question.id}`}
                              className="p-2 text-muted-foreground hover:text-foreground hover:bg-secondary rounded-lg transition-colors"
                              onClick={() => setEditingQuestionId(question.id)}
                            >
                              <Pencil className="w-4 h-4" />
                            </button>
                            {(selectedRound.feedback_questions || []).length > 1 && (
                              <button
                                id={`delete-question-btn-${question.id}`}
                                disabled={deletingQuestionId === question.id}
                                className="p-2 text-destructive hover:bg-destructive/10 rounded-lg transition-colors disabled:opacity-50"
                                onClick={() => deleteQuestion(selectedRound.id, question.id)}
                              >
                                {deletingQuestionId === question.id ? (
                                  <Loader2 className="w-4 h-4 animate-spin" />
                                ) : (
                                  <Trash2 className="w-4 h-4" />
                                )}
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>

                  <button
                    id="add-question-btn"
                    onClick={() => addQuestion(selectedRound.id)}
                    disabled={addingQuestionToRound === selectedRound.id}
                    className="mt-6 flex items-center gap-2 px-4 py-2 border border-border rounded-lg hover:bg-secondary transition-all duration-200 text-sm disabled:opacity-50"
                  >
                    {addingQuestionToRound === selectedRound.id ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Plus className="w-4 h-4" />
                    )}
                    {addingQuestionToRound === selectedRound.id ? "Adding..." : "Add Question"}
                  </button>
                </div>

                <div id="round-actions" className="flex justify-between mt-8">
                  <button
                    id="save-round-btn"
                    onClick={() => saveRound(selectedRound)}
                    disabled={savingRoundId === selectedRound.id}
                    className="flex items-center gap-2 px-6 py-3 border border-border rounded-lg hover:bg-secondary transition-all duration-200 disabled:opacity-50"
                  >
                    {savingRoundId === selectedRound.id ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Save className="w-4 h-4" />
                    )}
                    {savingRoundId === selectedRound.id ? "Saving..." : "Save Round"}
                  </button>
                  {selectedRoundIndex < plan.rounds.length - 1 ? (
                    <button
                      id="next-round-btn"
                      onClick={() => setSelectedRoundIndex(selectedRoundIndex + 1)}
                      className="flex items-center gap-2 px-8 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
                    >
                      Next Round
                      <ChevronRight className="w-4 h-4" />
                    </button>
                  ) : (
                    <button
                      id="save-all-btn"
                      onClick={handleSaveAll}
                      disabled={savingAll}
                      className="flex items-center gap-2 px-8 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-all duration-200 disabled:opacity-50"
                    >
                      {savingAll && <Loader2 className="w-4 h-4 animate-spin" />}
                      {savingAll ? "Saving..." : "Save All Changes"}
                    </button>
                  )}
                </div>
              </div>
            )}
          </main>
        </div>

        <footer id="edit-footer" className="bg-card border-t border-border px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="text-sm text-muted-foreground">
              {plan.total_rounds} rounds · {plan.total_duration_display} total
            </div>
            <div className="flex items-center gap-4">
              <button
                id="save-all-footer-btn"
                onClick={handleSaveAll}
                disabled={savingAll}
                className="flex items-center gap-2 px-6 py-2 border border-border rounded-lg hover:bg-secondary transition-all duration-200 disabled:opacity-50"
              >
                {savingAll ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Save className="w-4 h-4" />
                )}
                {savingAll ? "Saving..." : "Save All"}
              </button>
              <button
                id="finish-btn"
                onClick={handleFinish}
                disabled={savingAll || updatingStatus}
                className="flex items-center gap-2 px-8 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-all duration-200 disabled:opacity-50"
              >
                {(savingAll || updatingStatus) && <Loader2 className="w-4 h-4 animate-spin" />}
                {requisition.status === 'planned' ? 'Save & Close' : 'Publish & Close'}
              </button>
            </div>
          </div>
        </footer>

        {showDetailsPopup && selectedRound && (
          <div
            id="details-popup-overlay"
            className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 animate-in fade-in duration-200"
            onClick={() => {
              saveRound(selectedRound);
              setShowDetailsPopup(false);
            }}
          >
            <div
              id="details-popup"
              className="w-full max-w-2xl max-h-[85vh] bg-card border border-border rounded-2xl shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="p-6 border-b border-border flex items-center justify-between">
                <div className="flex items-center gap-3 flex-1">
                  <span className="font-bold text-xl">Round Details -</span>
                  <input
                    id="round-name-popup-input"
                    value={selectedRound.name}
                    onChange={(e) => handleRoundNameChange(selectedRound.id, e.target.value)}
                    className="font-bold text-xl h-10 w-48 px-2 border border-dashed border-border rounded-lg bg-background focus:outline-none focus:border-primary transition-colors"
                  />
                </div>
                <button
                  id="close-details-btn"
                  className="p-2 hover:bg-secondary rounded-lg transition-colors"
                  onClick={() => {
                    saveRound(selectedRound);
                    setShowDetailsPopup(false);
                  }}
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
              <div className="p-6 overflow-y-auto max-h-[calc(85vh-80px)] space-y-6">
                <div id="duration-field">
                  <label className="text-sm font-bold mb-2 block">Duration (minutes)</label>
                  <input
                    id="duration-input"
                    type="number"
                    min="15"
                    max="180"
                    step="15"
                    value={selectedRound.duration_minutes}
                    onChange={(e) => handleRoundDurationChange(selectedRound.id, parseInt(e.target.value) || 45)}
                    className="w-32 px-3 py-2 border border-border rounded-lg bg-background focus:outline-none focus:border-primary transition-colors"
                  />
                </div>

                <div id="description-field">
                  <label className="text-sm font-bold mb-2 block">Description</label>
                  <textarea
                    id="description-popup-input"
                    value={selectedRound.description}
                    onChange={(e) => handleRoundDescriptionChange(selectedRound.id, e.target.value)}
                    className="w-full min-h-[120px] p-3 text-sm border border-border rounded-lg bg-background resize-none focus:outline-none focus:border-primary transition-colors"
                  />
                </div>

                <div id="skills-field">
                  <label className="text-sm font-bold mb-2 block">Skills Tested</label>
                  <div className="flex flex-wrap gap-2 mb-3">
                    {selectedRound.skills.map((skill, idx) => (
                      <span
                        key={idx}
                        id={`skill-tag-${idx}`}
                        className="px-3 py-1.5 text-sm border border-border rounded-lg bg-background flex items-center gap-2 animate-in fade-in duration-200"
                      >
                        {skill}
                        <button
                          type="button"
                          onClick={() => removeSkill(selectedRound.id, idx)}
                          className="text-destructive hover:text-destructive/80 transition-colors"
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
                      className="h-10 flex-1 px-3 border border-border rounded-lg bg-background focus:outline-none focus:border-primary transition-colors"
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
            id="guidelines-popup-overlay"
            className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 animate-in fade-in duration-200"
            onClick={() => {
              saveRound(selectedRound);
              setShowGuidelinesPopup(false);
            }}
          >
            <div
              id="guidelines-popup"
              className="w-full max-w-3xl max-h-[90vh] bg-card border border-border rounded-2xl shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="p-6 border-b border-border flex items-center justify-between">
                <h3 className="font-bold text-xl">{selectedRound.name} - Guidelines</h3>
                <button
                  id="close-guidelines-btn"
                  className="p-2 hover:bg-secondary rounded-lg transition-colors"
                  onClick={() => {
                    saveRound(selectedRound);
                    setShowGuidelinesPopup(false);
                  }}
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
              <div className="p-6 overflow-y-auto max-h-[calc(90vh-80px)] space-y-4">
                {(selectedRound.guidelines || []).map((guideline, index) => (
                  <div key={index} id={`guideline-${index}`} className="border border-border rounded-xl p-4 space-y-3 animate-in fade-in duration-200">
                    <div className="flex items-start gap-3">
                      <span className="w-6 h-6 rounded-full bg-primary text-primary-foreground flex items-center justify-center text-sm flex-shrink-0 mt-1">
                        {index + 1}
                      </span>
                      <div className="flex-1 space-y-2">
                        <input
                          id={`guideline-title-${index}`}
                          value={guideline.title}
                          onChange={(e) => updateGuideline(selectedRound.id, index, "title", e.target.value)}
                          className="w-full font-semibold h-9 px-2 border border-dashed border-border rounded-lg bg-background focus:outline-none focus:border-primary transition-colors"
                          placeholder="Guideline title"
                        />
                        <textarea
                          id={`guideline-desc-${index}`}
                          value={guideline.description}
                          onChange={(e) => updateGuideline(selectedRound.id, index, "description", e.target.value)}
                          className="w-full min-h-[60px] p-2 text-sm text-muted-foreground border border-border rounded-lg bg-background resize-none focus:outline-none focus:border-primary transition-colors"
                          placeholder="Guideline description"
                        />
                      </div>
                      <button
                        type="button"
                        className="p-1.5 text-destructive hover:bg-destructive/10 rounded-lg transition-colors"
                        onClick={() => removeGuideline(selectedRound.id, index)}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                ))}

                <div id="add-guideline-section" className="border-2 border-dashed border-border rounded-xl p-4 space-y-3">
                  <p className="text-sm font-medium text-muted-foreground">Add New Guideline</p>
                  <input
                    id="new-guideline-title-input"
                    value={newGuidelineTitle}
                    onChange={(e) => setNewGuidelineTitle(e.target.value)}
                    placeholder="Guideline title"
                    className="w-full h-9 px-3 border border-border rounded-lg bg-background focus:outline-none focus:border-primary transition-colors"
                  />
                  <textarea
                    id="new-guideline-desc-input"
                    value={newGuidelineDesc}
                    onChange={(e) => setNewGuidelineDesc(e.target.value)}
                    placeholder="Guideline description (optional)"
                    className="w-full min-h-[60px] p-2 text-sm border border-border rounded-lg bg-background resize-none focus:outline-none focus:border-primary transition-colors"
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

        {showAddRoundModal && (
          <div
            id="add-round-modal-overlay"
            className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 animate-in fade-in duration-200"
            onClick={closeAddRoundModal}
          >
            <div
              id="add-round-modal"
              className="w-full max-w-3xl max-h-[90vh] bg-card border border-border rounded-2xl shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="p-6 border-b border-border flex items-center justify-between">
                <h3 className="font-bold text-xl">
                  {addRoundStep === "type" && "Add Round"}
                  {addRoundStep === "assessment-source" && "Add Assessment Round"}
                  {addRoundStep === "assessment-form" && "Create New Assessment"}
                </h3>
                <button
                  id="close-add-round-btn"
                  className="p-2 hover:bg-secondary rounded-lg transition-colors"
                  onClick={closeAddRoundModal}
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="p-6 overflow-y-auto max-h-[calc(90vh-80px)]">
                {addRoundStep === "type" && (
                  <div id="round-type-selection" className="space-y-4">
                    <p className="text-muted-foreground mb-6">What type of round do you want to add?</p>
                    <div className="grid grid-cols-2 gap-4">
                      <button
                        id="select-interview-round"
                        onClick={() => handleRoundTypeSelect("interview")}
                        disabled={addingRound}
                        className="p-6 border-2 border-border rounded-xl hover:border-primary hover:bg-primary/5 transition-all text-left group disabled:opacity-50"
                      >
                        <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center mb-4 group-hover:bg-primary/20 transition-colors">
                          <Users className="w-6 h-6 text-primary" />
                        </div>
                        <h4 className="font-semibold text-lg mb-1">Interview Round</h4>
                        <p className="text-sm text-muted-foreground">
                          Traditional interview with feedback questions and evaluation criteria
                        </p>
                      </button>

                      <button
                        id="select-assessment-round"
                        onClick={() => handleRoundTypeSelect("assessment")}
                        disabled={addingRound}
                        className="p-6 border-2 border-border rounded-xl hover:border-amber-500 hover:bg-amber-50 dark:hover:bg-amber-900/10 transition-all text-left group disabled:opacity-50"
                      >
                        <div className="w-12 h-12 rounded-xl bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center mb-4 group-hover:bg-amber-200 dark:group-hover:bg-amber-900/50 transition-colors">
                          <ClipboardList className="w-6 h-6 text-amber-600 dark:text-amber-400" />
                        </div>
                        <h4 className="font-semibold text-lg mb-1">Assessment Round</h4>
                        <p className="text-sm text-muted-foreground">
                          Task-based assessment with workspace tools and automated evaluation
                        </p>
                      </button>
                    </div>
                    {addingRound && (
                      <div className="flex items-center justify-center gap-2 mt-4 text-muted-foreground">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>Adding round...</span>
                      </div>
                    )}
                  </div>
                )}

                {addRoundStep === "assessment-source" && (
                  <div id="assessment-source-selection" className="space-y-6">
                    <div className="flex items-center gap-2 mb-4">
                      <button
                        id="back-to-type"
                        onClick={() => setAddRoundStep("type")}
                        className="p-2 hover:bg-secondary rounded-lg transition-colors"
                      >
                        <ArrowLeft className="w-4 h-4" />
                      </button>
                      <p className="text-muted-foreground">Choose assessment source</p>
                    </div>

                    <div className="grid grid-cols-2 gap-4 mb-6">
                      <button
                        id="select-library-source"
                        onClick={() => handleAssessmentSourceSelect("library")}
                        className={`p-4 border-2 rounded-xl transition-all text-left ${
                          assessmentSource === "library"
                            ? "border-primary bg-primary/5"
                            : "border-border hover:border-primary/50"
                        }`}
                      >
                        <FileJson className="w-6 h-6 text-primary mb-2" />
                        <h4 className="font-semibold">From Library</h4>
                        <p className="text-xs text-muted-foreground">Select an existing assessment template</p>
                      </button>

                      <button
                        id="select-new-source"
                        onClick={() => handleAssessmentSourceSelect("new")}
                        className={`p-4 border-2 rounded-xl transition-all text-left ${
                          assessmentSource === "new"
                            ? "border-primary bg-primary/5"
                            : "border-border hover:border-primary/50"
                        }`}
                      >
                        <Plus className="w-6 h-6 text-primary mb-2" />
                        <h4 className="font-semibold">Create New</h4>
                        <p className="text-xs text-muted-foreground">Create new assessment with JSON</p>
                      </button>
                    </div>

                    {assessmentSource === "library" && (
                      <div id="library-selection" className="space-y-4">
                        <h4 className="font-semibold">Select Assessment Template</h4>
                        {loadingTemplates ? (
                          <div className="flex items-center justify-center py-8">
                            <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
                          </div>
                        ) : assessmentTemplates.length === 0 ? (
                          <div className="text-center py-8 text-muted-foreground">
                            <ClipboardList className="w-12 h-12 mx-auto mb-2 opacity-50" />
                            <p>No published assessment templates found</p>
                            <button
                              onClick={() => handleAssessmentSourceSelect("new")}
                              className="mt-2 text-primary hover:underline text-sm"
                            >
                              Create a new assessment instead
                            </button>
                          </div>
                        ) : (
                          <div className="space-y-2 max-h-64 overflow-y-auto">
                            {assessmentTemplates.map((template) => (
                              <button
                                key={template.id}
                                id={`template-option-${template.id}`}
                                onClick={() => handleSelectTemplate(template.id)}
                                className={`w-full p-4 border rounded-xl text-left transition-all ${
                                  selectedTemplateId === template.id
                                    ? "border-primary bg-primary/5"
                                    : "border-border hover:border-primary/50"
                                }`}
                              >
                                <div className="flex items-start justify-between">
                                  <div>
                                    <h5 className="font-medium">{template.title}</h5>
                                    {template.description && (
                                      <p className="text-sm text-muted-foreground line-clamp-1">{template.description}</p>
                                    )}
                                    <div className="flex items-center gap-2 mt-2">
                                      <span className="text-xs px-2 py-0.5 bg-secondary rounded">
                                        {template.time_limit_minutes} mins
                                      </span>
                                      {template.role_seniority && (
                                        <span className="text-xs px-2 py-0.5 bg-secondary rounded">
                                          {template.role_seniority}
                                        </span>
                                      )}
                                    </div>
                                  </div>
                                  {selectedTemplateId === template.id && (
                                    <Check className="w-5 h-5 text-primary flex-shrink-0" />
                                  )}
                                </div>
                              </button>
                            ))}
                          </div>
                        )}

                        {selectedTemplateId && (
                          <div className="flex justify-end pt-4 border-t border-border">
                            <button
                              id="add-from-library-btn"
                              onClick={addAssessmentRoundFromLibrary}
                              disabled={addingRound}
                              className="flex items-center gap-2 px-6 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 disabled:opacity-50"
                            >
                              {addingRound ? (
                                <Loader2 className="w-4 h-4 animate-spin" />
                              ) : (
                                <Plus className="w-4 h-4" />
                              )}
                              {addingRound ? "Adding..." : "Add Assessment Round"}
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {addRoundStep === "assessment-form" && (
                  <div id="new-assessment-form" className="space-y-6">
                    <div className="flex items-center gap-2 mb-4">
                      <button
                        id="back-to-source"
                        onClick={() => setAddRoundStep("assessment-source")}
                        className="p-2 hover:bg-secondary rounded-lg transition-colors"
                      >
                        <ArrowLeft className="w-4 h-4" />
                      </button>
                      <p className="text-muted-foreground">Paste your Task Definition and Evaluation Rubric JSONs</p>
                    </div>

                    <div>
                      <label className="text-sm font-medium mb-1 block">
                        Task Definition JSON *
                        {taskJsonError && <span className="text-destructive ml-2">{taskJsonError}</span>}
                      </label>
                      <p className="text-xs text-muted-foreground mb-2">
                        Include <code className="bg-secondary px-1 rounded">scenario.title</code>, <code className="bg-secondary px-1 rounded">task_metadata.estimated_time</code>, and <code className="bg-secondary px-1 rounded">task_metadata.seniority_level</code>
                      </p>
                      <textarea
                        id="task-definition-json"
                        value={taskDefinitionJson}
                        onChange={(e) => {
                          setTaskDefinitionJson(e.target.value);
                          if (e.target.value) validateJson(e.target.value, "task");
                        }}
                        placeholder='{"scenario": {"title": "..."}, "task_metadata": {"estimated_time": 45, "seniority_level": "PM"}}'
                        rows={10}
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
                        id="eval-rubric-json"
                        value={evalRubricJson}
                        onChange={(e) => {
                          setEvalRubricJson(e.target.value);
                          if (e.target.value) validateJson(e.target.value, "eval");
                        }}
                        placeholder='{"dimensions": [...], "metadata": {"total_points": 100}}'
                        rows={10}
                        className={`w-full px-3 py-2 border rounded-lg bg-zinc-900 text-zinc-100 font-mono text-sm focus:outline-none resize-y ${
                          evalJsonError ? "border-destructive" : "border-border focus:border-primary"
                        }`}
                      />
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
                            id={`new-assessment-tool-${tool.id}`}
                            type="button"
                            onClick={() => toggleNewAssessmentTool(tool.id)}
                            className={`px-3 py-1.5 text-sm rounded-lg border transition-colors ${
                              newAssessmentTools.includes(tool.id)
                                ? "border-primary bg-primary/10 text-primary"
                                : "border-border hover:border-primary/50"
                            }`}
                          >
                            {tool.label}
                          </button>
                        ))}
                      </div>
                    </div>

                    {taskDefinitionJson.trim() && !taskJsonError && (() => {
                      const inferred = inferFromTaskJson(taskDefinitionJson, evalRubricJson);
                      return (
                        <div id="inferred-preview" className="bg-secondary/50 border border-border rounded-lg p-4">
                          <h4 className="text-sm font-medium mb-2">Inferred from JSON:</h4>
                          <div className="grid grid-cols-2 gap-2 text-sm">
                            <div><span className="text-muted-foreground">Title:</span> {inferred.title || <span className="italic text-muted-foreground">Not found</span>}</div>
                            <div><span className="text-muted-foreground">Duration:</span> {inferred.duration} mins</div>
                            <div><span className="text-muted-foreground">Tools:</span> {newAssessmentTools.map((t) => t === "excalidraw" ? "Whiteboard" : t === "voice_recorder" ? "Voice Recorder" : t).join(", ") || "None"}</div>
                            <div><span className="text-muted-foreground">Seniority:</span> {inferred.role_seniority || <span className="italic text-muted-foreground">Not found</span>}</div>
                          </div>
                        </div>
                      );
                    })()}

                    <div className="flex justify-end pt-4 border-t border-border">
                      <button
                        id="create-assessment-btn"
                        onClick={addNewAssessmentRound}
                        disabled={addingRound || !taskDefinitionJson.trim() || !evalRubricJson.trim()}
                        className="flex items-center gap-2 px-6 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 disabled:opacity-50"
                      >
                        {addingRound ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <Plus className="w-4 h-4" />
                        )}
                        {addingRound ? "Creating..." : "Create & Add Assessment"}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </AuthGuard>
  );
}
