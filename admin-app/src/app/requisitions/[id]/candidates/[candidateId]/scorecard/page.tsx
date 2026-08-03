"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Loader2, Save, Check, X, Plus, AlertTriangle, ChevronLeft, ChevronRight, Calendar, Link as LinkIcon, Video, Play, FileJson, Upload, Sparkles, Edit, Copy, FileText } from "lucide-react";
import Link from "next/link";
import { AuthGuard } from "@/components/auth-guard";
import { AdminNav } from "@/components/admin-nav";
import { createClient } from "@/lib/supabase/client";
import { RecordingStatus } from "@/components/recording-status";
import { VideoPlayer, VideoPlayerRef } from "@/components/video-player";
import { TranscriptViewer } from "@/components/transcript-viewer";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
// V2 backend base — these admin endpoints are ported to /api/v2/admin.
const API_V2_URL = process.env.NEXT_PUBLIC_API_V2_URL || "http://localhost:8004";

interface FeedbackEntry {
  id: string | null;
  feedback_data: string | null;
  evidence: string[];
  evidence_status: string | null;
  source: string | null;
}

interface FeedbackQuestion {
  id: string;
  question_number: number;
  heading: string;
  description: string | null;
  feedback: FeedbackEntry[];
  summary?: string | null;
}

interface RubricLevel {
  level: string;
  label: string;
  point_range: string;
  min_points: number;
  max_points: number;
  description: string;
  indicators: string[];
}

interface Criterion {
  criterion_id: string;
  criterion_name: string;
  criterion_description?: string;
  max_points: number;
  scoring_rubric: {
    excellent: RubricLevel;
    good: RubricLevel;
    adequate: RubricLevel;
    poor: RubricLevel;
  };
  common_pitfalls?: string[];
}

interface EvaluationCategory {
  category_name: string;
  category_description?: string;
  category_weight_percentage: number;
  criteria: Criterion[];
}

interface RubricMetadata {
  task_title?: string;
  role_seniority?: string;
  total_possible_points: number;
  passing_threshold_percentage: number;
}

interface AssessmentTemplate {
  id: string;
  title: string;
  description?: string;
  evaluation_rubric?: {
    rubric_metadata?: RubricMetadata;
    evaluation_categories?: EvaluationCategory[];
  };
  task_definition?: Record<string, unknown>;
}

interface CriterionScore {
  criterion_id: string;
  criterion_name: string;
  score: number;
  max_points: number;
  level: string;
  notes: string;
}

interface CategoryScore {
  category_name: string;
  category_index: number;
  weight_percentage: number;
  score: number;
  max_score: number;
  percentage: number;
  criterion_scores: CriterionScore[];
}

interface EvaluationResult {
  overall_score: number;
  total_possible_points: number;
  overall_percentage: number;
  passing_threshold: number;
  passed: boolean;
  category_scores: CategoryScore[];
  strengths?: string;
  areas_for_development?: string;
}

interface AssessmentInstance {
  id: string;
  status: string;
  access_url?: string;
  access_code?: string;
  access_code_expires_at?: string;
  started_at?: string;
  submitted_at?: string;
  submission_data?: Record<string, unknown>;
  work_data?: Record<string, unknown>;
  evaluation_result?: EvaluationResult;
  evaluation_notes?: string;
  evaluated_at?: string;
}

interface CriterionEvalState {
  criterion_id: string;
  criterion_name: string;
  max_points: number;
  score: number;
  level: string;
  notes: string;
}

interface CategoryEvalState {
  category_name: string;
  category_index: number;
  weight_percentage: number;
  criteria: CriterionEvalState[];
}

interface CandidateRound {
  id: string;
  round_id: string;
  round_name: string;
  round_number: number;
  round_category: string | null;
  round_type?: string;
  round_duration_minutes: number;
  round_description: string | null;
  status: string;
  scheduled_at: string | null;
  meeting_url: string | null;
  summary: string | null;
  rating: string | null;
  feedback_questions: FeedbackQuestion[];
  assessment_template?: AssessmentTemplate;
  assessment_instance?: AssessmentInstance;
}

interface Candidate {
  id: string;
  name: string;
  email: string;
  status: string;
  requisition_title: string;
  rounds: CandidateRound[];
}

interface FeedbackEntryState {
  id: string | null;
  feedback_data: string;
  evidence: string[];
  evidence_status: string | null;
}

export default function ScorecardEditorPage() {
  const params = useParams();
  const router = useRouter();
  const requisitionId = params.id as string;
  const candidateId = params.candidateId as string;

  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedRoundIndex, setSelectedRoundIndex] = useState(0);
  const [feedbackState, setFeedbackState] = useState<Record<string, FeedbackEntryState[]>>({});
  const [categoryEvaluations, setCategoryEvaluations] = useState<CategoryEvalState[]>([]);
  const [overallNotes, setOverallNotes] = useState("");
  const [strengths, setStrengths] = useState("");
  const [areasForDevelopment, setAreasForDevelopment] = useState("");
  const [roundSummary, setRoundSummary] = useState("");
  const [roundRating, setRoundRating] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [showScheduleModal, setShowScheduleModal] = useState(false);
  const [scheduleRoundId, setScheduleRoundId] = useState<string | null>(null);
  const [scheduleDate, setScheduleDate] = useState("");
  const [scheduleTime, setScheduleTime] = useState("");
  const [scheduleMeetingUrl, setScheduleMeetingUrl] = useState("");
  const [isScheduling, setIsScheduling] = useState(false);
  const [showRescheduleModal, setShowRescheduleModal] = useState(false);
  const [rescheduleExpirationDays, setRescheduleExpirationDays] = useState(3);
  const [isRescheduling, setIsRescheduling] = useState(false);
  const [assessmentInstanceData, setAssessmentInstanceData] = useState<{
    instance_id: string;
    access_url: string;
    access_code: string;
    expires_at: string;
  } | null>(null);
  const [viewMode, setViewMode] = useState<"scorecard" | "replay" | "import" | "ai" | "credentials">("scorecard");
  const [jsonInput, setJsonInput] = useState("");
  const [importError, setImportError] = useState("");
  const [importWarnings, setImportWarnings] = useState<string[]>([]);
  const [aiTranscript, setAiTranscript] = useState("");
  const [aiProcessing, setAiProcessing] = useState(false);
  const [aiError, setAiError] = useState("");
  const [aiSuccess, setAiSuccess] = useState("");
  const [summaryGenerating, setSummaryGenerating] = useState(false);
  const [transcriptStatus, setTranscriptStatus] = useState<{
    has_transcript: boolean;
    has_interview_segments: boolean;
    has_feedback_timestamp: boolean;
    has_stored_feedback: boolean;
    can_process_existing: boolean;
  } | null>(null);
  const [transcriptStatusLoading, setTranscriptStatusLoading] = useState(false);
  const [recordingData, setRecordingData] = useState<{
    status: string;
    scheduled_at?: string;
    video_url?: string;
    video_duration_seconds?: number;
    transcript?: any[];
    participants?: any[];
    error_code?: string;
    error_sub_code?: string;
  } | null>(null);
  const [recordingLoading, setRecordingLoading] = useState(false);
  const [currentVideoTime, setCurrentVideoTime] = useState(0);
  const videoPlayerRef = useRef<VideoPlayerRef>(null);

  const fetchCandidate = useCallback(async () => {
    setIsLoading(true);
    setError("");

    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        throw new Error("Not authenticated");
      }

      const response = await fetch(`${API_V2_URL}/api/v2/admin/candidates/${candidateId}`, {
        headers: {
          "Authorization": `Bearer ${session.access_token}`,
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) {
        throw new Error("Failed to fetch candidate");
      }

      const data = await response.json();
      console.log("[DEBUG] Fetched candidate data:", data);
      console.log("[DEBUG] Rounds with meeting_url:", data.rounds?.map((r: CandidateRound) => ({ name: r.round_name, meeting_url: r.meeting_url, scheduled_at: r.scheduled_at })));
      setCandidate(data);

      if (data.rounds && data.rounds.length > 0) {
        initializeRoundState(data.rounds[0]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load candidate");
    } finally {
      setIsLoading(false);
    }
  }, [candidateId]);

  const initializeRoundState = (round: CandidateRound) => {
    setRoundSummary(round.summary || "");
    setRoundRating(round.rating || "");

    const state: Record<string, FeedbackEntryState[]> = {};
    for (const q of round.feedback_questions || []) {
      const entries = (q.feedback || []).map(fb => ({
        id: fb.id,
        feedback_data: fb.feedback_data || "",
        evidence: fb.evidence || [],
        evidence_status: fb.evidence_status,
      }));
      state[q.id] = entries.length > 0 ? entries : [];
    }
    setFeedbackState(state);

    if (round.round_type === "assessment" && round.assessment_template?.evaluation_rubric?.evaluation_categories) {
      const categories = round.assessment_template.evaluation_rubric.evaluation_categories;
      const existingResult = round.assessment_instance?.evaluation_result;
      const existingNotes = round.assessment_instance?.evaluation_notes || "";

      setOverallNotes(existingNotes);
      setStrengths(existingResult?.strengths || "");
      setAreasForDevelopment(existingResult?.areas_for_development || "");

      const catEvals: CategoryEvalState[] = categories.map((cat, catIndex) => {
        const existingCatScore = existingResult?.category_scores?.find(c => c.category_index === catIndex);

        return {
          category_name: cat.category_name,
          category_index: catIndex,
          weight_percentage: cat.category_weight_percentage,
          criteria: cat.criteria.map(crit => {
            const existingCritScore = existingCatScore?.criterion_scores?.find(
              cs => cs.criterion_id === crit.criterion_id
            );
            return {
              criterion_id: crit.criterion_id,
              criterion_name: crit.criterion_name,
              max_points: crit.max_points,
              score: existingCritScore?.score ?? 0,
              level: existingCritScore?.level || "",
              notes: existingCritScore?.notes || "",
            };
          }),
        };
      });
      setCategoryEvaluations(catEvals);
    } else {
      setCategoryEvaluations([]);
      setOverallNotes("");
      setStrengths("");
      setAreasForDevelopment("");
    }
  };

  useEffect(() => {
    fetchCandidate();
  }, [fetchCandidate]);

  useEffect(() => {
    if (candidate?.rounds && candidate.rounds[selectedRoundIndex]) {
      initializeRoundState(candidate.rounds[selectedRoundIndex]);
    }
  }, [selectedRoundIndex, candidate]);

  const fetchRecording = useCallback(async (candidateRoundId: string) => {
    try {
      setRecordingLoading(true);
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) return;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/candidate-rounds/${candidateRoundId}/recording`, {
        headers: {
          "Authorization": `Bearer ${session.access_token}`,
          "Content-Type": "application/json",
        },
      });

      if (response.ok) {
        const data = await response.json();
        setRecordingData(data);
      } else {
        setRecordingData(null);
      }
    } catch (err) {
      console.error("Failed to fetch recording:", err);
      setRecordingData(null);
    } finally {
      setRecordingLoading(false);
    }
  }, []);

  useEffect(() => {
    if (viewMode === "replay" && candidate && candidate.rounds[selectedRoundIndex]) {
      const roundId = candidate.rounds[selectedRoundIndex].id;
      fetchRecording(roundId);
    }
  }, [viewMode, candidate, selectedRoundIndex, fetchRecording]);

  const handleTranscriptSeek = (timestamp: number) => {
    if (videoPlayerRef.current) {
      videoPlayerRef.current.seekTo(timestamp);
    }
  };

  const handleSave = async () => {
    if (!candidate) return;

    const currentRound = candidate.rounds[selectedRoundIndex];
    if (!currentRound) return;

    setIsSaving(true);
    setSaveError("");
    setSaveSuccess(false);

    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        throw new Error("Not authenticated");
      }

      if (currentRound.round_type === "assessment") {
        const categoryScores = categoryEvaluations.map(cat => ({
          category_name: cat.category_name,
          category_index: cat.category_index,
          weight_percentage: cat.weight_percentage,
          criterion_scores: cat.criteria.map(crit => ({
            criterion_id: crit.criterion_id,
            criterion_name: crit.criterion_name,
            score: crit.score ?? 0,
            max_points: crit.max_points,
            level: crit.level || "",
            notes: crit.notes || null,
          })),
        }));

        const response = await fetch(`${API_V2_URL}/api/v2/admin/candidate-rounds/${currentRound.id}/assessment-evaluation`, {
          method: "PUT",
          headers: {
            "Authorization": `Bearer ${session.access_token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            category_scores: categoryScores,
            overall_notes: overallNotes || null,
            strengths: strengths || null,
            areas_for_development: areasForDevelopment || null,
            round_summary: roundSummary || null,
            round_rating: roundRating || null,
          }),
        });

        if (!response.ok) {
          const errData = await response.json();
          throw new Error(errData.detail || "Failed to save assessment evaluation");
        }
      } else {
        const feedbackPayload: Array<{
          id?: string;
          feedback_question_id: string;
          feedback_data: string;
          evidence: string[];
          evidence_status: string;
        }> = [];

        for (const q of currentRound.feedback_questions || []) {
          const entries = feedbackState[q.id] || [];
          for (const entry of entries) {
            const evidence = (entry.evidence || []).filter(e => e.trim() !== "");
            feedbackPayload.push({
              ...(entry.id ? { id: entry.id } : {}),
              feedback_question_id: q.id,
              feedback_data: entry.feedback_data || "",
              evidence: evidence,
              evidence_status: evidence.length > 0 ? "supported" : "unsupported",
            });
          }
        }

        const response = await fetch(`${API_V2_URL}/api/v2/admin/candidate-rounds/${currentRound.id}/structured-feedback`, {
          method: "PUT",
          headers: {
            "Authorization": `Bearer ${session.access_token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            feedback: feedbackPayload,
            round_summary: roundSummary || null,
            round_rating: roundRating || null,
            source: "manual",
          }),
        });

        if (!response.ok) {
          const errData = await response.json();
          throw new Error(errData.detail || "Failed to save feedback");
        }
      }

      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);

      await fetchCandidate();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setIsSaving(false);
    }
  };

  const addFeedbackEntry = (questionId: string) => {
    setFeedbackState(prev => ({
      ...prev,
      [questionId]: [...(prev[questionId] || []), { id: null, feedback_data: "", evidence: [], evidence_status: null }],
    }));
  };

  const removeFeedbackEntry = (questionId: string, entryIndex: number) => {
    setFeedbackState(prev => ({
      ...prev,
      [questionId]: (prev[questionId] || []).filter((_, i) => i !== entryIndex),
    }));
  };

  const updateFeedbackEntry = (questionId: string, entryIndex: number, field: keyof FeedbackEntryState, value: string | string[] | null) => {
    setFeedbackState(prev => {
      const entries = [...(prev[questionId] || [])];
      if (entries[entryIndex]) {
        entries[entryIndex] = { ...entries[entryIndex], [field]: value };
      }
      return { ...prev, [questionId]: entries };
    });
  };

  const addEvidence = (questionId: string, entryIndex: number) => {
    const entries = feedbackState[questionId] || [];
    const current = entries[entryIndex]?.evidence || [];
    updateFeedbackEntry(questionId, entryIndex, "evidence", [...current, ""]);
  };

  const removeEvidence = (questionId: string, entryIndex: number, evidenceIndex: number) => {
    const entries = feedbackState[questionId] || [];
    const current = entries[entryIndex]?.evidence || [];
    updateFeedbackEntry(questionId, entryIndex, "evidence", current.filter((_, i) => i !== evidenceIndex));
  };

  const updateEvidence = (questionId: string, entryIndex: number, evidenceIndex: number, value: string) => {
    const entries = feedbackState[questionId] || [];
    const current = [...(entries[entryIndex]?.evidence || [])];
    current[evidenceIndex] = value;
    updateFeedbackEntry(questionId, entryIndex, "evidence", current);
  };

  const handleImportJson = () => {
    setImportError("");
    setImportWarnings([]);

    if (!jsonInput.trim()) {
      setImportError("Please paste JSON data");
      return;
    }

    if (!candidate) {
      setImportError("No candidate data loaded");
      return;
    }

    const currentRound = candidate.rounds[selectedRoundIndex];
    if (!currentRound) {
      setImportError("No round selected");
      return;
    }

    try {
      const data = JSON.parse(jsonInput);
      const warnings: string[] = [];

      if (data.round_summary !== undefined) {
        setRoundSummary(data.round_summary || "");
      }

      if (data.round_rating !== undefined) {
        const validRatings = ["strong_yes", "yes", "maybe", "no", "strong_no", ""];
        if (validRatings.includes(data.round_rating || "")) {
          setRoundRating(data.round_rating || "");
        } else {
          warnings.push(`Invalid round_rating "${data.round_rating}", skipped`);
        }
      }

      if (data.questions && Array.isArray(data.questions)) {
        const questionsByNumber: Record<number, FeedbackQuestion> = {};
        for (const q of currentRound.feedback_questions || []) {
          questionsByNumber[q.question_number] = q;
        }

        const newFeedbackState: Record<string, FeedbackEntryState[]> = { ...feedbackState };

        for (const importQ of data.questions) {
          const qNum = importQ.question_number;
          const matchedQuestion = questionsByNumber[qNum];

          if (!matchedQuestion) {
            warnings.push(`Question #${qNum} not found in this round, skipped`);
            continue;
          }

          if (importQ.heading && matchedQuestion.heading.toLowerCase() !== importQ.heading.toLowerCase()) {
            warnings.push(`Question #${qNum}: heading mismatch - expected "${matchedQuestion.heading}", got "${importQ.heading}"`);
          }

          if (importQ.feedbacks && Array.isArray(importQ.feedbacks)) {
            const entries: FeedbackEntryState[] = importQ.feedbacks.map((fb: { feedback_data?: string; evidence?: string[]; evidence_status?: string }) => ({
              id: null,
              feedback_data: fb.feedback_data || "",
              evidence: fb.evidence || [],
              evidence_status: fb.evidence_status,
            }));
            newFeedbackState[matchedQuestion.id] = entries;
          }
        }

        setFeedbackState(newFeedbackState);
      }

      setImportWarnings(warnings);

      if (warnings.length === 0) {
        setViewMode("scorecard");
        setJsonInput("");
      }
    } catch (err) {
      setImportError(`Invalid JSON: ${err instanceof Error ? err.message : "Parse error"}`);
    }
  };

  const fetchTranscriptStatus = useCallback(async (candidateRoundId: string) => {
    try {
      setTranscriptStatusLoading(true);
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) return;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/candidate-rounds/${candidateRoundId}/transcript-status`, {
        headers: {
          "Authorization": `Bearer ${session.access_token}`,
          "Content-Type": "application/json",
        },
      });

      if (response.ok) {
        const data = await response.json();
        setTranscriptStatus(data);
      } else {
        setTranscriptStatus(null);
      }
    } catch (err) {
      console.error("Failed to fetch transcript status:", err);
      setTranscriptStatus(null);
    } finally {
      setTranscriptStatusLoading(false);
    }
  }, []);

  useEffect(() => {
    if (viewMode === "ai" && candidate && candidate.rounds[selectedRoundIndex]) {
      const roundId = candidate.rounds[selectedRoundIndex].id;
      fetchTranscriptStatus(roundId);
    }
  }, [viewMode, candidate, selectedRoundIndex, fetchTranscriptStatus]);

  const handleAiProcess = async (mode: "existing" | "new") => {
    setAiError("");
    setAiSuccess("");

    if (mode === "new" && !aiTranscript.trim()) {
      setAiError("Please paste a feedback transcript");
      return;
    }

    if (!candidate) {
      setAiError("No candidate data loaded");
      return;
    }

    const currentRound = candidate.rounds[selectedRoundIndex];
    if (!currentRound) {
      setAiError("No round selected");
      return;
    }

    setAiProcessing(true);

    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        setAiError("Not authenticated");
        setAiProcessing(false);
        return;
      }

      const requestBody: { candidate_round_id: string; new_feedback_transcript?: string } = {
        candidate_round_id: currentRound.id
      };
      if (mode === "new") {
        requestBody.new_feedback_transcript = aiTranscript;
      }

      const response = await fetch(`${API_V2_URL}/api/v2/admin/feedback-jobs`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${session.access_token}`,
        },
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Failed to trigger feedback processing: ${response.status}`);
      }

      const result = await response.json();
      if (result.status === "accepted") {
        setAiSuccess("Feedback processing started! This may take 2-3 minutes. Refresh the page to see results.");
      } else {
        setAiSuccess(`Feedback job status: ${result.status}. ${result.reason || ""}`);
      }
      if (mode === "new") {
        setAiTranscript("");
      }

      await fetchCandidate();
      setViewMode("scorecard");
    } catch (err) {
      setAiError(err instanceof Error ? err.message : "Failed to process feedback");
    } finally {
      setAiProcessing(false);
    }
  };

  const handleGenerateSummaries = async () => {
    setAiError("");
    setAiSuccess("");

    if (!candidate) {
      setAiError("No candidate data loaded");
      return;
    }

    const currentRound = candidate.rounds[selectedRoundIndex];
    if (!currentRound) {
      setAiError("No round selected");
      return;
    }

    setSummaryGenerating(true);

    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        setAiError("Not authenticated");
        setSummaryGenerating(false);
        return;
      }

      const response = await fetch(`${API_V2_URL}/api/v2/admin/feedback-jobs`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${session.access_token}`,
        },
        body: JSON.stringify({ candidate_round_id: currentRound.id }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Failed to trigger feedback processing: ${response.status}`);
      }

      const result = await response.json();
      if (result.status === "accepted") {
        setAiSuccess("Feedback reprocessing started! Summaries will be generated. This may take 2-3 minutes.");
      } else {
        setAiSuccess(`Job status: ${result.status}. ${result.reason || ""}`);
      }

      await fetchCandidate();
      setViewMode("scorecard");
    } catch (err) {
      setAiError(err instanceof Error ? err.message : "Failed to generate summaries");
    } finally {
      setSummaryGenerating(false);
    }
  };

  const selectedRound = candidate?.rounds?.[selectedRoundIndex];

  const openScheduleModal = (round: CandidateRound) => {
    console.log("[DEBUG] Opening schedule modal for round:", round);
    console.log("[DEBUG] Round meeting_url:", round.meeting_url);
    setScheduleRoundId(round.id);
    if (round.scheduled_at) {
      const date = new Date(round.scheduled_at);
      setScheduleDate(date.toISOString().split("T")[0]);
      setScheduleTime(date.toTimeString().slice(0, 5));
    } else {
      setScheduleDate("");
      setScheduleTime("");
    }
    setScheduleMeetingUrl(round.meeting_url || "");
    setShowScheduleModal(true);
  };

  const handleSchedule = async () => {
    if (!scheduleRoundId) return;

    if (!scheduleDate) {
      setSaveError("Please select a date");
      return;
    }
    if (!scheduleTime) {
      setSaveError("Please select a time");
      return;
    }
    if (!scheduleMeetingUrl.trim()) {
      setSaveError("Please enter a meeting link");
      return;
    }

    setIsScheduling(true);
    setSaveError("");
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        throw new Error("Not authenticated");
      }

      const scheduledDateTime = `${scheduleDate}T${scheduleTime}:00`;

      const requestBody = {
        scheduled_at: scheduledDateTime,
        meeting_url: scheduleMeetingUrl.trim(),
      };

      const response = await fetch(`${API_V2_URL}/api/v2/admin/candidate-rounds/${scheduleRoundId}/schedule`, {
        method: "PUT",
        headers: {
          "Authorization": `Bearer ${session.access_token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || "Failed to schedule interview");
      }

      setShowScheduleModal(false);
      await fetchCandidate();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to schedule");
    } finally {
      setIsScheduling(false);
    }
  };

  const handleRescheduleAssessment = async () => {
    if (!candidate) return;

    const currentRound = candidate.rounds[selectedRoundIndex];
    if (!currentRound) return;

    setIsRescheduling(true);
    setSaveError("");

    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        throw new Error("Not authenticated");
      }

      const response = await fetch(`${API_V2_URL}/api/v2/admin/candidate-rounds/${currentRound.id}/reschedule-assessment?expiration_days=${rescheduleExpirationDays}`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${session.access_token}`,
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || "Failed to reschedule assessment");
      }

      const data = await response.json();
      setAssessmentInstanceData({
        instance_id: data.instance_id,
        access_url: data.access_url,
        access_code: data.access_code,
        expires_at: data.expires_at,
      });
      setShowRescheduleModal(false);
      await fetchCandidate();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to reschedule");
    } finally {
      setIsRescheduling(false);
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
  };

  return (
    <AuthGuard>
      <div id="scorecard-editor-page" className="min-h-screen bg-background">
        <AdminNav />

        <main id="scorecard-main-content" className="max-w-7xl mx-auto px-6 py-8">
          <div id="scorecard-back-nav" className="mb-6">
            <button
              id="scorecard-back-btn"
              onClick={() => router.back()}
              className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              Back to Candidates
            </button>
          </div>

          {error && (
            <div id="scorecard-error-alert" className="mb-6 p-4 bg-destructive/10 border border-destructive/20 rounded-lg text-destructive flex items-center gap-2">
              <AlertTriangle className="w-5 h-5" />
              {error}
            </div>
          )}

          {isLoading ? (
            <div id="scorecard-loading" className="flex items-center justify-center h-64">
              <Loader2 className="w-8 h-8 animate-spin text-primary" />
            </div>
          ) : candidate ? (
            <div id="scorecard-content" className="flex gap-6">
              <aside id="scorecard-sidebar" className="w-64 flex-shrink-0">
                <div id="scorecard-candidate-info" className="bg-card border border-border rounded-xl p-4 mb-4">
                  <h2 id="scorecard-candidate-name" className="font-bold text-lg">{candidate.name}</h2>
                  <p className="text-sm text-muted-foreground">{candidate.email}</p>
                  <p className="text-sm text-muted-foreground mt-1">{candidate.requisition_title}</p>
                </div>

                <div id="scorecard-rounds-nav" className="bg-card border border-border rounded-xl overflow-hidden">
                  <div className="px-4 py-3 border-b border-border bg-secondary/30">
                    <h3 className="text-sm font-medium text-muted-foreground">Interview Rounds</h3>
                  </div>
                  <div id="scorecard-rounds-list" className="divide-y divide-border">
                    {candidate.rounds.map((round, index) => (
                      <div
                        key={round.id}
                        className={`flex items-center justify-between px-4 py-3 transition-colors ${
                          selectedRoundIndex === index
                            ? "bg-primary/10"
                            : "hover:bg-secondary/50"
                        }`}
                      >
                        <button
                          id={`scorecard-round-btn-${round.id}`}
                          onClick={() => setSelectedRoundIndex(index)}
                          className="flex-1 text-left"
                        >
                          <div className="flex items-center gap-2">
                            <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs ${
                              round.status === "completed"
                                ? "bg-primary text-primary-foreground"
                                : round.status === "scheduled"
                                ? "bg-blue-500 text-white"
                                : "bg-secondary border border-border"
                            }`}>
                              {round.status === "completed" ? (
                                <Check className="w-3 h-3" />
                              ) : round.status === "scheduled" ? (
                                <Calendar className="w-3 h-3" />
                              ) : (
                                round.round_number
                              )}
                            </span>
                            <div className="min-w-0">
                              <span className={`text-sm font-medium truncate block ${
                                selectedRoundIndex === index ? "text-primary" : ""
                              }`}>
                                {round.round_name}
                              </span>
                              {round.scheduled_at && (
                                <span className="text-xs text-muted-foreground">
                                  {new Date(round.scheduled_at).toLocaleDateString()}
                                </span>
                              )}
                            </div>
                          </div>
                        </button>
                        <button
                          id={`scorecard-schedule-btn-${round.id}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            openScheduleModal(round);
                          }}
                          className="ml-2 p-1.5 text-muted-foreground hover:text-primary hover:bg-primary/10 rounded-md transition-colors"
                          title={round.scheduled_at ? "Reschedule" : "Schedule"}
                        >
                          <Calendar className="w-4 h-4" />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              </aside>

              <div id="scorecard-main-form" className="flex-1 min-w-0">
                {selectedRound ? (
                  <>
                    <div id="scorecard-header" className="flex items-center justify-between mb-6">
                      <div>
                        <h1 id="scorecard-round-title" className="text-xl font-bold">
                          Round {selectedRound.round_number}: {selectedRound.round_name}
                        </h1>
                        {selectedRound.round_description && (
                          <p className="text-sm text-muted-foreground mt-1">{selectedRound.round_description}</p>
                        )}
                        {selectedRound.scheduled_at && (
                          <div className="flex items-center gap-2 mt-2 text-sm">
                            <Calendar className="w-4 h-4 text-blue-500" />
                            <span className="text-muted-foreground">
                              Scheduled: {new Date(selectedRound.scheduled_at).toLocaleString()}
                            </span>
                            {selectedRound.meeting_url && (
                              <a
                                id="scorecard-meeting-link"
                                href={selectedRound.meeting_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="flex items-center gap-1 text-primary hover:underline"
                              >
                                <LinkIcon className="w-3 h-3" />
                                Meeting Link
                              </a>
                            )}
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-3">
                        <button
                          id="scorecard-schedule-round-btn"
                          onClick={() => openScheduleModal(selectedRound)}
                          className="flex items-center gap-2 px-4 py-2 border border-border rounded-lg hover:bg-secondary transition-colors"
                        >
                          <Calendar className="w-4 h-4" />
                          {selectedRound.scheduled_at ? "Reschedule" : "Schedule"}
                        </button>
                        <button
                          id="scorecard-prev-round"
                          onClick={() => setSelectedRoundIndex(Math.max(0, selectedRoundIndex - 1))}
                          disabled={selectedRoundIndex === 0}
                          className="p-2 border border-border rounded-lg hover:bg-secondary disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          <ChevronLeft className="w-4 h-4" />
                        </button>
                        <button
                          id="scorecard-next-round"
                          onClick={() => setSelectedRoundIndex(Math.min((candidate.rounds.length || 1) - 1, selectedRoundIndex + 1))}
                          disabled={selectedRoundIndex === (candidate.rounds.length || 1) - 1}
                          className="p-2 border border-border rounded-lg hover:bg-secondary disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          <ChevronRight className="w-4 h-4" />
                        </button>
                      </div>
                    </div>

                    <div id="scorecard-view-tabs" className="flex items-center gap-4 mb-6 border-b border-border">
                      <button
                        id="scorecard-tab-btn"
                        onClick={() => setViewMode("scorecard")}
                        className={`pb-3 px-1 text-sm font-medium border-b-2 transition-colors ${
                          viewMode === "scorecard"
                            ? "border-primary text-primary"
                            : "border-transparent text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        Scorecard
                      </button>
                      {selectedRound?.round_type === "assessment" && selectedRound?.assessment_instance && (
                        <button
                          id="credentials-tab-btn"
                          onClick={() => setViewMode("credentials")}
                          className={`pb-3 px-1 text-sm font-medium border-b-2 transition-colors flex items-center gap-2 ${
                            viewMode === "credentials"
                              ? "border-primary text-primary"
                              : "border-transparent text-muted-foreground hover:text-foreground"
                          }`}
                        >
                          <LinkIcon className="w-4 h-4" />
                          Credentials
                        </button>
                      )}
                      {selectedRound?.round_type !== "assessment" && (
                        <>
                          <button
                            id="replay-tab-btn"
                            onClick={() => setViewMode("replay")}
                            className={`pb-3 px-1 text-sm font-medium border-b-2 transition-colors flex items-center gap-2 ${
                              viewMode === "replay"
                                ? "border-primary text-primary"
                                : "border-transparent text-muted-foreground hover:text-foreground"
                            }`}
                          >
                            <Video className="w-4 h-4" />
                            Replay
                          </button>
                          <button
                            id="import-tab-btn"
                            onClick={() => setViewMode("import")}
                            className={`pb-3 px-1 text-sm font-medium border-b-2 transition-colors flex items-center gap-2 ${
                              viewMode === "import"
                                ? "border-primary text-primary"
                                : "border-transparent text-muted-foreground hover:text-foreground"
                            }`}
                          >
                            <FileJson className="w-4 h-4" />
                            JSON Import
                          </button>
                          <button
                            id="ai-process-tab-btn"
                            onClick={() => setViewMode("ai")}
                            className={`pb-3 px-1 text-sm font-medium border-b-2 transition-colors flex items-center gap-2 ${
                              viewMode === "ai"
                                ? "border-primary text-primary"
                                : "border-transparent text-muted-foreground hover:text-foreground"
                            }`}
                          >
                            <Sparkles className="w-4 h-4" />
                            AI Process
                          </button>
                        </>
                      )}
                    </div>

                    {viewMode === "scorecard" ? (
                      <>
                    <div id="scorecard-round-summary-section" className="bg-card border border-border rounded-xl p-5 mb-6">
                      <h3 className="font-medium mb-4">{selectedRound.round_type === "assessment" ? "Round Verdict" : "Round Summary & Verdict"}</h3>
                      <div className="space-y-4">
                        {selectedRound.round_type !== "assessment" && (
                          <div>
                            <label id="scorecard-summary-label" className="block text-sm font-medium mb-2">Summary</label>
                            <textarea
                              id="scorecard-summary-input"
                              value={roundSummary}
                              onChange={(e) => setRoundSummary(e.target.value)}
                              placeholder="Enter overall round summary..."
                              rows={3}
                              className="w-full px-4 py-3 bg-secondary/50 rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none"
                            />
                          </div>
                        )}
                        <div>
                          <label id="scorecard-rating-label" className="block text-sm font-medium mb-2">Round Verdict</label>
                          <select
                            id="scorecard-rating-select"
                            value={roundRating}
                            onChange={(e) => setRoundRating(e.target.value)}
                            className="w-full px-4 py-3 bg-secondary/50 rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-primary/50"
                          >
                            <option value="">Pending</option>
                            <option value="strong_yes">Strong Yes</option>
                            <option value="yes">Yes</option>
                            <option value="maybe">Maybe</option>
                            <option value="no">No</option>
                            <option value="strong_no">Strong No</option>
                          </select>
                        </div>
                      </div>
                    </div>

                    {selectedRound.round_type === "assessment" && selectedRound.assessment_template ? (
                      <div id="assessment-evaluation-section" className="space-y-4">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-3">
                            <h3 className="font-medium text-muted-foreground">Assessment Evaluation</h3>
                            <Link
                              id="edit-assessment-link"
                              href={`/assessments/${selectedRound.assessment_template.id}`}
                              className="flex items-center gap-1 text-xs text-primary hover:underline"
                            >
                              <Edit className="w-3 h-3" />
                              Edit Assessment
                            </Link>
                          </div>
                          <div className="flex items-center gap-3">
                            <button
                              id="reschedule-assessment-btn"
                              onClick={() => setShowRescheduleModal(true)}
                              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-secondary hover:bg-secondary/80 rounded-lg transition-colors"
                            >
                              <Calendar className="w-3.5 h-3.5" />
                              {selectedRound.assessment_instance ? "Reschedule" : "Schedule"} Assessment
                            </button>
                            {selectedRound.assessment_instance && (
                              <span className={`px-2 py-1 text-xs rounded-full ${
                                selectedRound.assessment_instance.status === "submitted" || selectedRound.assessment_instance.status === "evaluated"
                                  ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                                  : selectedRound.assessment_instance.status === "in_progress"
                                  ? "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400"
                                  : "bg-gray-100 text-gray-700 dark:bg-gray-900/30 dark:text-gray-400"
                              }`}>
                                {selectedRound.assessment_instance.status?.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase())}
                              </span>
                            )}
                          </div>
                        </div>

                        {(() => {
                          const rubric = selectedRound.assessment_template.evaluation_rubric;
                          const metadata = rubric?.rubric_metadata;
                          const categories = rubric?.evaluation_categories || [];
                          const totalPossiblePoints = metadata?.total_possible_points || 100;
                          const passingThreshold = metadata?.passing_threshold_percentage || 70;

                          const totalEarnedPoints = categoryEvaluations.reduce((sum, cat) =>
                            sum + cat.criteria.reduce((catSum, crit) => catSum + crit.score, 0), 0
                          );
                          const overallPercentage = totalPossiblePoints > 0
                            ? Math.round((totalEarnedPoints / totalPossiblePoints) * 100)
                            : 0;
                          const passed = overallPercentage >= passingThreshold;

                          return (
                            <>
                              {metadata && (
                                <div id="assessment-rubric-header" className="bg-card border border-border rounded-xl p-4">
                                  <div className="flex items-center justify-between">
                                    <div>
                                      <h4 className="font-medium">{metadata.task_title || "Assessment"}</h4>
                                      <p className="text-sm text-muted-foreground">{metadata.role_seniority}</p>
                                    </div>
                                    <div className="flex items-center gap-4">
                                      <div className="text-center px-4 py-2 bg-secondary rounded-lg">
                                        <p className="text-xs text-muted-foreground">Points</p>
                                        <p className="text-lg font-bold">{totalEarnedPoints}/{totalPossiblePoints}</p>
                                      </div>
                                      <div className={`text-center px-6 py-3 rounded-xl ${
                                        passed ? "bg-green-100 dark:bg-green-900/30" :
                                        overallPercentage >= passingThreshold - 15 ? "bg-amber-100 dark:bg-amber-900/30" :
                                        "bg-red-100 dark:bg-red-900/30"
                                      }`}>
                                        <p className="text-xs text-muted-foreground">Score</p>
                                        <p className={`text-2xl font-bold ${
                                          passed ? "text-green-700 dark:text-green-400" :
                                          overallPercentage >= passingThreshold - 15 ? "text-amber-700 dark:text-amber-400" :
                                          "text-red-700 dark:text-red-400"
                                        }`}>{overallPercentage}%</p>
                                        <p className="text-xs text-muted-foreground">
                                          {passed ? "PASS" : "BELOW THRESHOLD"} ({passingThreshold}%)
                                        </p>
                                      </div>
                                    </div>
                                  </div>
                                </div>
                              )}

                              {categories.map((category, catIndex) => {
                                const catEval = categoryEvaluations.find(c => c.category_index === catIndex);
                                const catMaxPoints = category.criteria.reduce((sum, c) => sum + c.max_points, 0);
                                const catEarnedPoints = catEval?.criteria.reduce((sum, c) => sum + c.score, 0) || 0;
                                const catPercentage = catMaxPoints > 0 ? Math.round((catEarnedPoints / catMaxPoints) * 100) : 0;

                                return (
                                  <div
                                    key={`cat-${catIndex}`}
                                    id={`assessment-category-${catIndex}`}
                                    className="bg-card border border-border rounded-xl p-5"
                                  >
                                    <div className="mb-4">
                                      <div className="flex items-center justify-between">
                                        <div>
                                          <h4 id={`assessment-category-heading-${catIndex}`} className="font-medium">
                                            {catIndex + 1}. {category.category_name}
                                          </h4>
                                          {category.category_description && (
                                            <p className="text-sm text-muted-foreground mt-1">{category.category_description}</p>
                                          )}
                                        </div>
                                        <div className="flex items-center gap-3">
                                          <span className="text-xs text-muted-foreground">
                                            Weight: {category.category_weight_percentage}%
                                          </span>
                                          <span className={`px-2 py-1 rounded-lg text-sm font-medium ${
                                            catPercentage >= 80 ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" :
                                            catPercentage >= 60 ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400" :
                                            "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
                                          }`}>
                                            {catEarnedPoints}/{catMaxPoints} pts
                                          </span>
                                        </div>
                                      </div>
                                    </div>

                                    <div className="space-y-4">
                                      {category.criteria.map((criterion, critIndex) => {
                                        const critEval = catEval?.criteria.find(c => c.criterion_id === criterion.criterion_id);
                                        const levels = ["excellent", "good", "adequate", "poor"] as const;

                                        return (
                                          <div
                                            key={`crit-${critIndex}`}
                                            id={`criterion-${catIndex}-${critIndex}`}
                                            className="border border-border rounded-lg p-4 bg-secondary/20"
                                          >
                                            <div className="flex items-start justify-between mb-3">
                                              <div className="flex-1">
                                                <h5 className="font-medium text-sm">{criterion.criterion_name}</h5>
                                                {criterion.criterion_description && (
                                                  <p className="text-xs text-muted-foreground mt-1">{criterion.criterion_description}</p>
                                                )}
                                                <p className="text-xs text-muted-foreground mt-1">
                                                  Max Points: {criterion.max_points}
                                                </p>
                                              </div>
                                              <div className="ml-4 text-right">
                                                <span className={`text-lg font-bold ${
                                                  critEval && critEval.score >= criterion.max_points * 0.8 ? "text-green-600" :
                                                  critEval && critEval.score >= criterion.max_points * 0.6 ? "text-amber-600" :
                                                  critEval && critEval.score > 0 ? "text-red-600" : "text-muted-foreground"
                                                }`}>
                                                  {critEval?.score || 0}
                                                </span>
                                                <span className="text-sm text-muted-foreground">/{criterion.max_points}</span>
                                              </div>
                                            </div>

                                            <div className="grid grid-cols-4 gap-2 mb-3">
                                              {levels.map(level => {
                                                const rubricLevel = criterion.scoring_rubric?.[level];
                                                if (!rubricLevel) return null;
                                                const isSelected = critEval?.level === level;
                                                const levelColors = {
                                                  excellent: "border-green-500 bg-green-50 dark:bg-green-900/20",
                                                  good: "border-blue-500 bg-blue-50 dark:bg-blue-900/20",
                                                  adequate: "border-amber-500 bg-amber-50 dark:bg-amber-900/20",
                                                  poor: "border-red-500 bg-red-50 dark:bg-red-900/20",
                                                };
                                                const selectedColors = {
                                                  excellent: "bg-green-500 text-white border-green-600",
                                                  good: "bg-blue-500 text-white border-blue-600",
                                                  adequate: "bg-amber-500 text-white border-amber-600",
                                                  poor: "bg-red-500 text-white border-red-600",
                                                };

                                                return (
                                                  <button
                                                    key={level}
                                                    id={`criterion-${catIndex}-${critIndex}-${level}`}
                                                    type="button"
                                                    onClick={() => {
                                                      const avgPoints = Math.round(((rubricLevel.min_points || 0) + (rubricLevel.max_points || 0)) / 2);
                                                      setCategoryEvaluations(prev => prev.map(cat =>
                                                        cat.category_index === catIndex
                                                          ? {
                                                              ...cat,
                                                              criteria: cat.criteria.map(c =>
                                                                c.criterion_id === criterion.criterion_id
                                                                  ? { ...c, score: avgPoints, level }
                                                                  : c
                                                              ),
                                                            }
                                                          : cat
                                                      ));
                                                    }}
                                                    className={`p-2 rounded-lg border-2 text-left transition-all ${
                                                      isSelected ? selectedColors[level] : `${levelColors[level]} hover:opacity-80`
                                                    }`}
                                                  >
                                                    <div className="text-xs font-semibold capitalize">{rubricLevel.label || level}</div>
                                                    <div className={`text-xs ${isSelected ? "text-white/80" : "text-muted-foreground"}`}>
                                                      {rubricLevel.point_range}
                                                    </div>
                                                  </button>
                                                );
                                              })}
                                            </div>

                                            {critEval?.level && criterion.scoring_rubric?.[critEval.level as keyof typeof criterion.scoring_rubric] && (
                                              <div className="text-xs text-muted-foreground mb-3 p-2 bg-secondary rounded">
                                                <strong>Selected Level:</strong> {criterion.scoring_rubric[critEval.level as keyof typeof criterion.scoring_rubric]?.description}
                                              </div>
                                            )}

                                            <div className="flex items-center gap-3 mb-2">
                                              <label className="text-xs font-medium">Points:</label>
                                              <div className="flex items-center gap-1">
                                                <input
                                                  id={`criterion-score-${catIndex}-${critIndex}`}
                                                  type="text"
                                                  inputMode="numeric"
                                                  pattern="[0-9]*"
                                                  value={critEval?.score ?? ""}
                                                  onChange={(e) => {
                                                    const value = e.target.value;
                                                    if (value === "" || /^\d+$/.test(value)) {
                                                      const numValue = value === "" ? 0 : parseInt(value, 10);
                                                      const newScore = Math.min(Math.max(0, numValue), criterion.max_points);
                                                      let newLevel = "";
                                                      for (const lvl of levels) {
                                                        const rubricLvl = criterion.scoring_rubric?.[lvl];
                                                        if (rubricLvl && newScore >= rubricLvl.min_points && newScore <= rubricLvl.max_points) {
                                                          newLevel = lvl;
                                                          break;
                                                        }
                                                      }
                                                      setCategoryEvaluations(prev => prev.map(cat =>
                                                        cat.category_index === catIndex
                                                          ? {
                                                              ...cat,
                                                              criteria: cat.criteria.map(c =>
                                                                c.criterion_id === criterion.criterion_id
                                                                  ? { ...c, score: newScore, level: newLevel }
                                                                  : c
                                                              ),
                                                            }
                                                          : cat
                                                      ));
                                                    }
                                                  }}
                                                  onFocus={(e) => e.target.select()}
                                                  className="w-16 px-3 py-1.5 text-center text-sm font-medium bg-background rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-primary/50"
                                                />
                                                <span className="text-sm text-muted-foreground">/ {criterion.max_points}</span>
                                              </div>
                                            </div>

                                            <textarea
                                              id={`criterion-notes-${catIndex}-${critIndex}`}
                                              value={critEval?.notes || ""}
                                              onChange={(e) => {
                                                setCategoryEvaluations(prev => prev.map(cat =>
                                                  cat.category_index === catIndex
                                                    ? {
                                                        ...cat,
                                                        criteria: cat.criteria.map(c =>
                                                          c.criterion_id === criterion.criterion_id
                                                            ? { ...c, notes: e.target.value }
                                                            : c
                                                        ),
                                                      }
                                                    : cat
                                                ));
                                              }}
                                              placeholder="Add notes for this criterion..."
                                              rows={2}
                                              className="w-full px-2 py-1.5 text-sm bg-background rounded border border-border focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none"
                                            />
                                          </div>
                                        );
                                      })}
                                    </div>
                                  </div>
                                );
                              })}

                              <div id="evaluation-summary-section" className="bg-card border border-border rounded-xl p-5 space-y-4">
                                <div>
                                  <label className="block text-sm font-medium mb-2 text-green-700 dark:text-green-400">Strengths</label>
                                  <textarea
                                    id="evaluation-strengths"
                                    value={strengths}
                                    onChange={(e) => setStrengths(e.target.value)}
                                    placeholder="Key strengths demonstrated in this assessment..."
                                    rows={3}
                                    className="w-full px-3 py-2 bg-green-50 dark:bg-green-900/20 rounded-lg border border-green-200 dark:border-green-800 focus:outline-none focus:ring-2 focus:ring-green-500/50 resize-none text-sm"
                                  />
                                </div>
                                <div>
                                  <label className="block text-sm font-medium mb-2 text-amber-700 dark:text-amber-400">Areas for Development</label>
                                  <textarea
                                    id="evaluation-areas-for-development"
                                    value={areasForDevelopment}
                                    onChange={(e) => setAreasForDevelopment(e.target.value)}
                                    placeholder="Areas where improvement is needed..."
                                    rows={3}
                                    className="w-full px-3 py-2 bg-amber-50 dark:bg-amber-900/20 rounded-lg border border-amber-200 dark:border-amber-800 focus:outline-none focus:ring-2 focus:ring-amber-500/50 resize-none text-sm"
                                  />
                                </div>
                                <div>
                                  <label className="block text-sm font-medium mb-2">Additional Notes</label>
                                  <textarea
                                    id="overall-evaluation-notes"
                                    value={overallNotes}
                                    onChange={(e) => setOverallNotes(e.target.value)}
                                    placeholder="Any additional evaluation notes..."
                                    rows={2}
                                    className="w-full px-3 py-2 bg-background rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none text-sm"
                                  />
                                </div>
                              </div>
                            </>
                          );
                        })()}

                        {(!selectedRound.assessment_template.evaluation_rubric?.evaluation_categories ||
                          selectedRound.assessment_template.evaluation_rubric.evaluation_categories.length === 0) && (
                          <div className="text-center py-8 text-muted-foreground">
                            No evaluation categories defined for this assessment
                          </div>
                        )}

                        {!selectedRound.assessment_instance && (
                          <div id="assessment-not-started-notice" className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-4 text-sm text-amber-800 dark:text-amber-400">
                            <AlertTriangle className="w-4 h-4 inline mr-2" />
                            Note: The candidate has not started this assessment yet. You can still fill in evaluations to be ready when they submit.
                          </div>
                        )}
                      </div>
                    ) : (
                      <div id="scorecard-questions-section" className="space-y-4">
                        <h3 className="font-medium text-muted-foreground">Evaluation Criteria</h3>

                        {(selectedRound.feedback_questions || []).map((question) => (
                          <div
                            key={question.id}
                            id={`scorecard-question-${question.id}`}
                            className="bg-card border border-border rounded-xl p-5"
                          >
                            <div className="mb-4">
                              <h4 id={`scorecard-question-heading-${question.id}`} className="font-medium">
                                {question.question_number}. {question.heading}
                              </h4>
                              {question.description && (
                                <p id={`scorecard-question-desc-${question.id}`} className="text-sm text-muted-foreground mt-1">
                                  {question.description}
                                </p>
                              )}
                              {question.summary && (
                                <div
                                  id={`scorecard-question-summary-${question.id}`}
                                  className="mt-3 p-3 bg-primary/5 rounded-lg border border-primary/20"
                                >
                                  <div className="flex items-center justify-between mb-1">
                                    <span className="text-xs font-semibold text-primary uppercase tracking-wide">
                                      AI Summary
                                    </span>
                                    <button
                                      id={`scorecard-copy-summary-${question.id}`}
                                      onClick={() => {
                                        navigator.clipboard.writeText(question.summary || "");
                                      }}
                                      className="p-1 hover:bg-primary/10 rounded transition-colors"
                                      title="Copy summary"
                                    >
                                      <Copy className="w-3 h-3 text-primary" />
                                    </button>
                                  </div>
                                  <p className="text-sm">{question.summary}</p>
                                </div>
                              )}
                            </div>

                            <div className="space-y-4">
                              {(feedbackState[question.id] || []).map((entry, entryIndex) => (
                                <div
                                  key={entry.id || `new-${entryIndex}`}
                                  id={`scorecard-feedback-entry-${question.id}-${entryIndex}`}
                                  className="bg-secondary/30 rounded-lg p-4 border border-border/50"
                                >
                                  <div className="flex items-start justify-between mb-3">
                                    <span className="text-xs text-muted-foreground font-medium">
                                      Feedback {entryIndex + 1}
                                    </span>
                                    <div className="flex items-center gap-2">
                                      {(() => {
                                        const hasEvidence = (entry.evidence || []).filter(e => e.trim() !== "").length > 0;
                                        const isContradicted = entry.evidence_status === "contradicted";
                                        const isSupported = hasEvidence && (entry.evidence_status === "verified" || entry.evidence_status === "supported" || !isContradicted);

                                        if (isContradicted) {
                                          return (
                                            <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400">
                                              Contradicted
                                            </span>
                                          );
                                        } else if (isSupported) {
                                          return (
                                            <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
                                              Supported
                                            </span>
                                          );
                                        } else {
                                          return (
                                            <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400">
                                              Not Supported
                                            </span>
                                          );
                                        }
                                      })()}
                                      <button
                                        id={`scorecard-remove-feedback-${question.id}-${entryIndex}`}
                                        onClick={() => removeFeedbackEntry(question.id, entryIndex)}
                                        className="p-1 text-destructive hover:bg-destructive/10 rounded transition-colors"
                                        title="Remove feedback"
                                      >
                                        <X className="w-4 h-4" />
                                      </button>
                                    </div>
                                  </div>

                                  <textarea
                                    id={`scorecard-feedback-text-${question.id}-${entryIndex}`}
                                    value={entry.feedback_data || ""}
                                    onChange={(e) => updateFeedbackEntry(question.id, entryIndex, "feedback_data", e.target.value)}
                                    placeholder="Enter feedback..."
                                    rows={2}
                                    className="w-full px-3 py-2 bg-background rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none text-sm mb-3"
                                  />

                                  <div id={`scorecard-evidence-section-${question.id}-${entryIndex}`}>
                                    <label className="block text-xs text-muted-foreground font-medium mb-2">Evidence</label>
                                    <div className="space-y-2">
                                      {(entry.evidence || []).map((ev, evidenceIndex) => (
                                        <div key={evidenceIndex} className="flex gap-2">
                                          <input
                                            id={`scorecard-evidence-input-${question.id}-${entryIndex}-${evidenceIndex}`}
                                            value={ev}
                                            onChange={(e) => updateEvidence(question.id, entryIndex, evidenceIndex, e.target.value)}
                                            placeholder="Enter evidence quote..."
                                            className="flex-1 px-3 py-1.5 text-sm bg-background rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-primary/50"
                                          />
                                          <button
                                            id={`scorecard-remove-evidence-${question.id}-${entryIndex}-${evidenceIndex}`}
                                            onClick={() => removeEvidence(question.id, entryIndex, evidenceIndex)}
                                            className="px-2 py-1.5 text-destructive hover:bg-destructive/10 rounded transition-colors"
                                          >
                                            <X className="w-3 h-3" />
                                          </button>
                                        </div>
                                      ))}
                                      <button
                                        id={`scorecard-add-evidence-${question.id}-${entryIndex}`}
                                        onClick={() => addEvidence(question.id, entryIndex)}
                                        className="flex items-center gap-1 text-xs text-primary hover:underline"
                                      >
                                        <Plus className="w-3 h-3" />
                                        Add Evidence
                                      </button>
                                    </div>
                                  </div>
                                </div>
                              ))}

                              <button
                                id={`scorecard-add-feedback-${question.id}`}
                                onClick={() => addFeedbackEntry(question.id)}
                                className="flex items-center gap-2 text-sm text-primary hover:underline w-full justify-center py-2 border border-dashed border-primary/30 rounded-lg hover:bg-primary/5 transition-colors"
                              >
                                <Plus className="w-4 h-4" />
                                Add Feedback
                              </button>
                            </div>
                          </div>
                        ))}

                        {(!selectedRound.feedback_questions || selectedRound.feedback_questions.length === 0) && (
                          <div className="text-center py-8 text-muted-foreground">
                            No evaluation criteria defined for this round
                          </div>
                        )}
                      </div>
                    )}

                    <div id="scorecard-save-section" className="mt-6 flex items-center justify-end gap-4">
                      {saveError && (
                        <span className="text-sm text-destructive">{saveError}</span>
                      )}
                      {saveSuccess && (
                        <span className="text-sm text-green-600 dark:text-green-400 flex items-center gap-1">
                          <Check className="w-4 h-4" />
                          Saved successfully
                        </span>
                      )}
                      <button
                        id="scorecard-copy-all-summaries-btn"
                        onClick={() => {
                          if (!selectedRound) return;
                          const lines: string[] = [];
                          lines.push(`# ${selectedRound.round_name} - Feedback Summary`);
                          lines.push("");
                          for (const question of selectedRound.feedback_questions || []) {
                            lines.push(`## ${question.question_number}. ${question.heading}`);
                            if (question.summary) {
                              lines.push(question.summary);
                            } else {
                              lines.push("_No summary available_");
                            }
                            lines.push("");
                          }
                          copyToClipboard(lines.join("\n"));
                        }}
                        className="flex items-center gap-2 px-4 py-2.5 border border-border rounded-lg hover:bg-secondary transition-colors"
                        title="Copy all summaries as markdown"
                      >
                        <Copy className="w-4 h-4" />
                        Copy All Summaries
                      </button>
                      <button
                        id="scorecard-save-btn"
                        onClick={handleSave}
                        disabled={isSaving}
                        className="flex items-center gap-2 px-6 py-2.5 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
                      >
                        {isSaving ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <Save className="w-4 h-4" />
                        )}
                        {isSaving ? "Saving..." : "Save Changes"}
                      </button>
                    </div>
                      </>
                    ) : viewMode === "replay" ? (
                      <div id="replay-content" className="flex flex-col h-full">
                        <div id="replay-status" className="mb-4">
                          <RecordingStatus
                            candidateRoundId={selectedRound.id}
                            status={recordingData?.status || "not_scheduled"}
                            scheduledAt={recordingData?.scheduled_at || selectedRound.scheduled_at}
                          />
                        </div>

                        {recordingLoading ? (
                          <div id="replay-loading" className="flex items-center justify-center py-12">
                            <div className="text-center">
                              <Loader2 className="w-8 h-8 animate-spin mx-auto mb-2 text-primary" />
                              <p className="text-sm text-muted-foreground">Loading recording...</p>
                            </div>
                          </div>
                        ) : recordingData?.video_url ? (
                          <div id="replay-video-transcript" className="flex flex-col lg:flex-row gap-6">
                            <div id="video-section" className="w-full lg:w-[60%] flex flex-col min-w-0">
                              <VideoPlayer
                                id={`video-player-${selectedRound.id}`}
                                ref={videoPlayerRef}
                                videoUrl={recordingData.video_url}
                                duration={recordingData.video_duration_seconds}
                                onTimeUpdate={setCurrentVideoTime}
                              />
                            </div>

                            <div id="transcript-section" className="w-full lg:w-[40%] bg-card rounded-xl border border-border p-4 min-h-[400px] flex flex-col">
                              <h3 id="transcript-title" className="font-semibold mb-3">Transcript</h3>
                              <div className="flex-1 overflow-hidden">
                                <TranscriptViewer
                                  id={`transcript-viewer-${selectedRound.id}`}
                                  transcript={recordingData.transcript || []}
                                  currentVideoTime={currentVideoTime}
                                  onSeek={handleTranscriptSeek}
                                />
                              </div>
                            </div>
                          </div>
                        ) : (
                          <div id="replay-placeholder" className="flex items-center justify-center py-12">
                            <div className="text-center">
                              <div className="w-16 h-16 rounded-full bg-secondary flex items-center justify-center mx-auto mb-4">
                                <Video className="w-8 h-8 text-muted-foreground" />
                              </div>
                              <p className="text-muted-foreground">
                                {recordingData?.status === "in_call_recording" ? "Recording in progress..." :
                                 recordingData?.status === "processing" ? "Processing recording..." :
                                 recordingData?.status === "failed" ? `Recording failed${recordingData.error_code ? `: ${recordingData.error_code}` : ""}` :
                                 "No recording available"}
                              </p>
                              {!recordingData?.status && selectedRound.meeting_url && (
                                <p className="text-sm text-muted-foreground mt-2">
                                  Recording will appear after the meeting ends
                                </p>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    ) : viewMode === "import" ? (
                      <div id="import-content" className="space-y-4">
                        <div className="bg-card border border-border rounded-xl p-5">
                          <h3 className="font-medium mb-4 flex items-center gap-2">
                            <FileJson className="w-5 h-5" />
                            Import Feedback from JSON
                          </h3>
                          <p className="text-sm text-muted-foreground mb-4">
                            Paste JSON data to auto-fill the scorecard. Questions are matched by <code className="bg-secondary px-1 rounded">question_number</code>.
                          </p>

                          <div className="bg-secondary/30 rounded-lg p-3 mb-4 text-xs font-mono overflow-x-auto">
                            <pre>{`{
  "round_summary": "Overall assessment...",
  "round_rating": "yes",
  "questions": [
    {
      "question_number": 1,
      "heading": "AI/LLM Comfort",
      "feedbacks": [
        {
          "feedback_data": "Feedback text...",
          "evidence": ["Quote 1...", "Quote 2..."]
        }
      ]
    }
  ]
}`}</pre>
                          </div>

                          <textarea
                            id="json-import-input"
                            value={jsonInput}
                            onChange={(e) => setJsonInput(e.target.value)}
                            placeholder="Paste your JSON here..."
                            rows={12}
                            className="w-full px-4 py-3 bg-secondary/50 rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-primary/50 font-mono text-sm resize-none"
                          />

                          {importError && (
                            <div className="mt-3 p-3 bg-destructive/10 border border-destructive/20 rounded-lg text-destructive text-sm flex items-start gap-2">
                              <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                              {importError}
                            </div>
                          )}

                          {importWarnings.length > 0 && (
                            <div className="mt-3 p-3 bg-orange-100 dark:bg-orange-900/20 border border-orange-200 dark:border-orange-800 rounded-lg text-orange-700 dark:text-orange-400 text-sm">
                              <p className="font-medium mb-2">Import completed with warnings:</p>
                              <ul className="list-disc list-inside space-y-1">
                                {importWarnings.map((w, i) => (
                                  <li key={i}>{w}</li>
                                ))}
                              </ul>
                              <button
                                onClick={() => { setViewMode("scorecard"); setJsonInput(""); setImportWarnings([]); }}
                                className="mt-3 text-primary hover:underline text-sm"
                              >
                                Go to Scorecard to review &rarr;
                              </button>
                            </div>
                          )}

                          <div className="mt-4 flex items-center gap-3">
                            <button
                              id="import-json-btn"
                              onClick={handleImportJson}
                              className="flex items-center gap-2 px-6 py-2.5 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
                            >
                              <Upload className="w-4 h-4" />
                              Import & Fill Scorecard
                            </button>
                            <button
                              onClick={() => { setJsonInput(""); setImportError(""); setImportWarnings([]); }}
                              className="px-4 py-2.5 border border-border rounded-lg hover:bg-secondary transition-colors"
                            >
                              Clear
                            </button>
                          </div>
                        </div>

                        <div className="bg-card border border-border rounded-xl p-5">
                          <h4 className="font-medium mb-3">Current Round Questions</h4>
                          <p className="text-sm text-muted-foreground mb-3">
                            Use these question numbers in your JSON:
                          </p>
                          <div className="space-y-2">
                            {(selectedRound.feedback_questions || []).map((q) => (
                              <div key={q.id} className="flex items-center gap-3 text-sm">
                                <span className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-primary font-medium">
                                  {q.question_number}
                                </span>
                                <span className="text-foreground">{q.heading}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    ) : viewMode === "ai" ? (
                      <div id="ai-process-content" className="space-y-4">
                        {aiError && (
                          <div className="p-3 bg-destructive/10 border border-destructive/20 rounded-lg text-destructive text-sm flex items-start gap-2">
                            <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                            {aiError}
                          </div>
                        )}

                        {aiSuccess && (
                          <div className="p-3 bg-green-100 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg text-green-700 dark:text-green-400 text-sm flex items-start gap-2">
                            <Check className="w-4 h-4 mt-0.5 flex-shrink-0" />
                            {aiSuccess}
                          </div>
                        )}

                        <div id="process-existing-section" className="bg-card border border-border rounded-xl p-5">
                          <h3 className="font-medium mb-2 flex items-center gap-2">
                            <Play className="w-5 h-5 text-primary" />
                            Process Existing Transcript
                          </h3>
                          <p className="text-sm text-muted-foreground mb-4">
                            Re-run AI processing on the existing interview/feedback transcript already captured by the recording bot.
                          </p>

                          {transcriptStatusLoading ? (
                            <div className="flex items-center gap-2 text-sm text-muted-foreground">
                              <Loader2 className="w-4 h-4 animate-spin" />
                              Checking transcript status...
                            </div>
                          ) : transcriptStatus?.can_process_existing ? (
                            <div className="space-y-3">
                              <div className="flex flex-wrap gap-2 text-xs">
                                {transcriptStatus.has_interview_segments && (
                                  <span className="px-2 py-1 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded-full">
                                    Interview segments available
                                  </span>
                                )}
                                {transcriptStatus.has_feedback_timestamp && (
                                  <span className="px-2 py-1 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 rounded-full">
                                    Feedback timestamp detected
                                  </span>
                                )}
                                {transcriptStatus.has_stored_feedback && (
                                  <span className="px-2 py-1 bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400 rounded-full">
                                    Stored feedback transcript
                                  </span>
                                )}
                              </div>
                              <button
                                id="process-existing-btn"
                                onClick={() => handleAiProcess("existing")}
                                disabled={aiProcessing}
                                className="flex items-center gap-2 px-6 py-2.5 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                              >
                                {aiProcessing ? (
                                  <>
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                    Processing...
                                  </>
                                ) : (
                                  <>
                                    <Play className="w-4 h-4" />
                                    Process Existing
                                  </>
                                )}
                              </button>
                            </div>
                          ) : (
                            <div className="p-3 bg-secondary/50 rounded-lg text-sm text-muted-foreground">
                              No existing transcript found. Use &quot;Add New Feedback&quot; below to manually provide feedback.
                            </div>
                          )}
                        </div>

                        <div id="generate-summaries-section" className="bg-card border border-border rounded-xl p-5">
                          <h3 className="font-medium mb-2 flex items-center gap-2">
                            <FileText className="w-5 h-5 text-primary" />
                            Generate Summaries
                          </h3>
                          <p className="text-sm text-muted-foreground mb-4">
                            Generate AI summaries for each feedback question from existing feedback data. Use this if feedback exists but summaries are missing.
                          </p>
                          <button
                            id="generate-summaries-btn"
                            onClick={handleGenerateSummaries}
                            disabled={summaryGenerating || aiProcessing}
                            className="flex items-center gap-2 px-6 py-2.5 bg-secondary text-secondary-foreground rounded-lg hover:bg-secondary/80 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            {summaryGenerating ? (
                              <>
                                <Loader2 className="w-4 h-4 animate-spin" />
                                Generating...
                              </>
                            ) : (
                              <>
                                <FileText className="w-4 h-4" />
                                Generate Summaries
                              </>
                            )}
                          </button>
                        </div>

                        <div id="add-new-feedback-section" className="bg-card border border-border rounded-xl p-5">
                          <h3 className="font-medium mb-2 flex items-center gap-2">
                            <Sparkles className="w-5 h-5 text-primary" />
                            Add New Feedback
                          </h3>
                          <p className="text-sm text-muted-foreground mb-4">
                            Manually paste a feedback transcript. This will replace any existing feedback transcript and process it through AI.
                          </p>

                          <textarea
                            id="ai-transcript-input"
                            value={aiTranscript}
                            onChange={(e) => setAiTranscript(e.target.value)}
                            placeholder="Paste the feedback transcript here...

Example:
'The candidate showed good product sense. They asked clarifying questions about the user problem before jumping to solutions.
Their prioritization was decent but could have been more structured.
Overall verdict: Yes, would recommend moving forward.'"
                            rows={10}
                            className="w-full px-4 py-3 bg-secondary/50 rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-primary/50 text-sm resize-none"
                            disabled={aiProcessing}
                          />

                          <div className="mt-4 flex items-center gap-3">
                            <button
                              id="process-new-btn"
                              onClick={() => handleAiProcess("new")}
                              disabled={aiProcessing || !aiTranscript.trim()}
                              className="flex items-center gap-2 px-6 py-2.5 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              {aiProcessing ? (
                                <>
                                  <Loader2 className="w-4 h-4 animate-spin" />
                                  Processing...
                                </>
                              ) : (
                                <>
                                  <Sparkles className="w-4 h-4" />
                                  Process New Feedback
                                </>
                              )}
                            </button>
                            <button
                              onClick={() => { setAiTranscript(""); setAiError(""); setAiSuccess(""); }}
                              disabled={aiProcessing}
                              className="px-4 py-2.5 border border-border rounded-lg hover:bg-secondary transition-colors disabled:opacity-50"
                            >
                              Clear
                            </button>
                          </div>
                        </div>

                        <div className="bg-card border border-border rounded-xl p-5">
                          <h4 className="font-medium mb-3">How it works</h4>
                          <ol className="text-sm text-muted-foreground space-y-2 list-decimal list-inside">
                            <li>The AI extracts feedback points from the feedback transcript</li>
                            <li>Feedback is mapped to the scorecard questions</li>
                            <li>Evidence is extracted from the full interview transcript to support each point</li>
                            <li>The scorecard is automatically populated with ratings and evidence</li>
                          </ol>
                        </div>

                        <div className="bg-card border border-border rounded-xl p-5">
                          <h4 className="font-medium mb-3">Current Round Questions</h4>
                          <div className="space-y-2">
                            {(selectedRound.feedback_questions || []).map((q) => (
                              <div key={q.id} className="flex items-center gap-3 text-sm">
                                <span className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-primary font-medium">
                                  {q.question_number}
                                </span>
                                <span className="text-foreground">{q.heading}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    ) : viewMode === "credentials" ? (
                      <div id="credentials-content" className="space-y-4">
                        {selectedRound?.assessment_instance ? (
                          <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-6">
                            <h3 className="font-medium text-amber-800 dark:text-amber-300 mb-4 flex items-center gap-2">
                              <LinkIcon className="w-5 h-5" />
                              Assessment Credentials
                            </h3>
                            <div className="space-y-4">
                              <div className="bg-white dark:bg-zinc-900 rounded-lg p-4">
                                <div className="flex items-center justify-between mb-2">
                                  <label className="text-sm font-medium text-amber-700 dark:text-amber-400">Access URL</label>
                                  <button
                                    id="creds-copy-url-btn"
                                    onClick={() => copyToClipboard(selectedRound.assessment_instance!.access_url || "")}
                                    className="text-xs text-amber-600 hover:text-amber-800 dark:text-amber-400 underline flex items-center gap-1"
                                  >
                                    <Copy className="w-3 h-3" />
                                    Copy
                                  </button>
                                </div>
                                <code className="block text-sm bg-secondary/50 p-3 rounded truncate">{selectedRound.assessment_instance.access_url}</code>
                              </div>

                              <div className="bg-white dark:bg-zinc-900 rounded-lg p-4">
                                <div className="flex items-center justify-between mb-2">
                                  <label className="text-sm font-medium text-amber-700 dark:text-amber-400">Access Code</label>
                                  <button
                                    id="creds-copy-code-btn"
                                    onClick={() => copyToClipboard(selectedRound.assessment_instance!.access_code || "")}
                                    className="text-xs text-amber-600 hover:text-amber-800 dark:text-amber-400 underline flex items-center gap-1"
                                  >
                                    <Copy className="w-3 h-3" />
                                    Copy
                                  </button>
                                </div>
                                <code className="block text-2xl font-mono tracking-wider bg-secondary/50 p-3 rounded">{selectedRound.assessment_instance.access_code}</code>
                              </div>

                              <div className="flex items-center justify-between text-sm">
                                <span className="text-amber-600 dark:text-amber-500">
                                  Expires: {selectedRound.assessment_instance.access_code_expires_at
                                    ? new Date(selectedRound.assessment_instance.access_code_expires_at).toLocaleDateString()
                                    : "N/A"}
                                </span>
                                <span className={`px-2 py-1 rounded text-xs font-medium ${
                                  selectedRound.assessment_instance.status === "evaluated"
                                    ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400"
                                    : selectedRound.assessment_instance.status === "submitted"
                                    ? "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400"
                                    : selectedRound.assessment_instance.status === "in_progress"
                                    ? "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400"
                                    : "bg-secondary text-muted-foreground"
                                }`}>
                                  {selectedRound.assessment_instance.status}
                                </span>
                              </div>

                              <div className="pt-4 border-t border-amber-200 dark:border-amber-800">
                                <button
                                  id="creds-copy-all-btn"
                                  onClick={() => {
                                    const text = `Assessment URL: ${selectedRound.assessment_instance!.access_url}\nAccess Code: ${selectedRound.assessment_instance!.access_code}`;
                                    copyToClipboard(text);
                                  }}
                                  className="w-full px-4 py-2.5 bg-amber-600 text-white rounded-lg hover:bg-amber-700 transition-colors flex items-center justify-center gap-2"
                                >
                                  <Copy className="w-4 h-4" />
                                  Copy All Details
                                </button>
                              </div>
                            </div>
                          </div>
                        ) : (
                          <div className="text-center py-12 text-muted-foreground">
                            <p>No assessment instance found for this round.</p>
                            <p className="text-sm mt-2">Schedule the assessment to generate credentials.</p>
                          </div>
                        )}
                      </div>
                    ) : null}
                  </>
                ) : (
                  <div className="text-center py-12 text-muted-foreground">
                    Select a round to edit
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="text-center py-12 text-muted-foreground">
              Candidate not found
            </div>
          )}
        </main>

        {showScheduleModal && (
          <div id="schedule-modal-overlay" className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
            <div id="schedule-modal" className="bg-card border border-border rounded-xl p-6 w-full max-w-md mx-4 shadow-xl">
              <h3 id="schedule-modal-title" className="text-lg font-semibold mb-4">
                {candidate?.rounds.find(r => r.id === scheduleRoundId)?.scheduled_at ? "Reschedule Interview" : "Schedule Interview"}
              </h3>
              <p id="schedule-modal-round-name" className="text-sm text-muted-foreground mb-4">
                Round: {candidate?.rounds.find(r => r.id === scheduleRoundId)?.round_name}
              </p>

              <div className="space-y-4">
                <div className="flex gap-3">
                  <div className="flex-1">
                    <label id="schedule-date-label" className="block text-xs text-muted-foreground mb-1">Date *</label>
                    <input
                      id="schedule-date-input"
                      type="date"
                      value={scheduleDate}
                      onChange={(e) => setScheduleDate(e.target.value)}
                      className="w-full px-4 py-2.5 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                    />
                  </div>
                  <div className="flex-1">
                    <label id="schedule-time-label" className="block text-xs text-muted-foreground mb-1">Time</label>
                    <input
                      id="schedule-time-input"
                      type="time"
                      value={scheduleTime}
                      onChange={(e) => setScheduleTime(e.target.value)}
                      className="w-full px-4 py-2.5 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                    />
                  </div>
                </div>
                <div>
                  <label id="schedule-meeting-url-label" className="block text-xs text-muted-foreground mb-1">
                    <span className="flex items-center gap-1">
                      <LinkIcon className="w-3 h-3" />
                      Meeting URL
                    </span>
                  </label>
                  <input
                    id="schedule-meeting-url-input"
                    type="url"
                    placeholder="https://meet.google.com/..."
                    value={scheduleMeetingUrl}
                    onChange={(e) => setScheduleMeetingUrl(e.target.value)}
                    className="w-full px-4 py-2.5 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                </div>
              </div>

              <div className="mt-6 flex justify-end gap-3">
                <button
                  id="schedule-cancel-btn"
                  onClick={() => {
                    setShowScheduleModal(false);
                    setScheduleRoundId(null);
                  }}
                  className="px-4 py-2 border border-border rounded-lg hover:bg-secondary transition-colors"
                >
                  Cancel
                </button>
                <button
                  id="schedule-confirm-btn"
                  onClick={handleSchedule}
                  disabled={!scheduleDate || isScheduling}
                  className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 flex items-center gap-2"
                >
                  {isScheduling ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Scheduling...
                    </>
                  ) : (
                    <>
                      <Calendar className="w-4 h-4" />
                      {candidate?.rounds.find(r => r.id === scheduleRoundId)?.scheduled_at ? "Reschedule" : "Schedule"}
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        )}

        {showRescheduleModal && (
          <div id="reschedule-assessment-modal-overlay" className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
            <div id="reschedule-assessment-modal" className="bg-card border border-border rounded-xl p-6 w-full max-w-md mx-4 shadow-xl">
              <h3 id="reschedule-modal-title" className="text-lg font-semibold mb-4">
                {selectedRound?.assessment_instance ? "Reschedule Assessment" : "Schedule Assessment"}
              </h3>
              <p className="text-sm text-muted-foreground mb-4">
                This will create a new assessment link and access code for the candidate.
                {selectedRound?.assessment_instance && " The previous link will be invalidated."}
              </p>

              <div className="space-y-4">
                <div>
                  <label id="reschedule-expiration-label" className="block text-sm font-medium mb-2">Link Expires In</label>
                  <select
                    id="reschedule-expiration-select"
                    value={rescheduleExpirationDays}
                    onChange={(e) => setRescheduleExpirationDays(Number(e.target.value))}
                    className="w-full px-4 py-2.5 border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                  >
                    <option value={1}>1 day</option>
                    <option value={3}>3 days</option>
                    <option value={5}>5 days</option>
                    <option value={7}>7 days</option>
                    <option value={14}>14 days</option>
                    <option value={30}>30 days</option>
                  </select>
                </div>
              </div>

              <div className="mt-6 flex justify-end gap-3">
                <button
                  id="reschedule-cancel-btn"
                  onClick={() => setShowRescheduleModal(false)}
                  className="px-4 py-2 border border-border rounded-lg hover:bg-secondary transition-colors"
                >
                  Cancel
                </button>
                <button
                  id="reschedule-confirm-btn"
                  onClick={handleRescheduleAssessment}
                  disabled={isRescheduling}
                  className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 flex items-center gap-2"
                >
                  {isRescheduling ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Creating...
                    </>
                  ) : (
                    <>
                      <Calendar className="w-4 h-4" />
                      Create Assessment Link
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        )}

        {assessmentInstanceData && (
          <div id="assessment-instance-modal-overlay" className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
            <div id="assessment-instance-modal" className="bg-card border border-border rounded-xl p-6 w-full max-w-md mx-4 shadow-xl">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-full bg-green-100 dark:bg-green-900/30 flex items-center justify-center">
                  <Check className="w-5 h-5 text-green-600 dark:text-green-400" />
                </div>
                <h3 className="text-lg font-semibold">Assessment Scheduled</h3>
              </div>

              <p className="text-sm text-muted-foreground mb-4">
                Share these details with the candidate:
              </p>

              <div className="space-y-3 mb-6">
                <div className="bg-secondary/50 rounded-lg p-3">
                  <label className="text-xs text-muted-foreground block mb-1">Assessment URL</label>
                  <div className="flex items-center gap-2">
                    <code className="text-sm flex-1 truncate">{assessmentInstanceData.access_url}</code>
                    <button
                      id="copy-assessment-url-btn"
                      onClick={() => copyToClipboard(assessmentInstanceData.access_url)}
                      className="p-1.5 hover:bg-secondary rounded text-muted-foreground hover:text-foreground"
                      title="Copy URL"
                    >
                      <Copy className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                <div className="bg-secondary/50 rounded-lg p-3">
                  <label className="text-xs text-muted-foreground block mb-1">Access Code</label>
                  <div className="flex items-center gap-2">
                    <code className="text-xl font-mono tracking-wider">{assessmentInstanceData.access_code}</code>
                    <button
                      id="copy-access-code-btn"
                      onClick={() => copyToClipboard(assessmentInstanceData.access_code)}
                      className="p-1.5 hover:bg-secondary rounded text-muted-foreground hover:text-foreground"
                      title="Copy Code"
                    >
                      <Copy className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                <p className="text-xs text-muted-foreground">
                  Code expires: {new Date(assessmentInstanceData.expires_at).toLocaleDateString()}
                </p>
              </div>

              <div className="flex gap-3">
                <button
                  id="copy-all-details-btn"
                  onClick={() => {
                    const text = `Assessment URL: ${assessmentInstanceData.access_url}\nAccess Code: ${assessmentInstanceData.access_code}`;
                    copyToClipboard(text);
                  }}
                  className="flex-1 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
                >
                  Copy All Details
                </button>
                <button
                  id="close-instance-modal-btn"
                  onClick={() => setAssessmentInstanceData(null)}
                  className="px-4 py-2 border border-border rounded-lg hover:bg-secondary transition-colors"
                >
                  Done
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </AuthGuard>
  );
}
