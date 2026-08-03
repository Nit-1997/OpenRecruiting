"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Mail, Loader2, Users, Edit, Trash2, RotateCcw, AlertTriangle, Briefcase, MapPin, Check, Calendar, Play, Plus, X } from "lucide-react";
import { AuthGuard } from "@/components/auth-guard";
import { AdminNav } from "@/components/admin-nav";
import { createClient } from "@/lib/supabase/client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// V2 backend base — admin endpoints ported to /api/v2/admin.

const API_V2_URL = process.env.NEXT_PUBLIC_API_V2_URL || "http://localhost:8004";
const CACHE_DURATION = 3 * 60 * 1000;

interface Requisition {
  id: string;
  organization_id: string;
  role_title: string;
  role_location: string;
  experience_display: string;
  status: string;
}

interface CandidateRound {
  id: string;
  round_name: string;
  round_number: number;
  status: "pending" | "scheduled" | "in_progress" | "completed" | "cancelled";
  scheduled_at: string | null;
  completed_at: string | null;
  outcome: "advance" | "reject" | "hold" | null;
}

interface Candidate {
  id: string;
  requisition_id: string;
  name: string;
  email: string;
  phone: string | null;
  status: "active" | "hired" | "rejected" | "withdrawn";
  final_verdict: "strong_hire" | "hire" | "no_hire" | "strong_no_hire" | null;
  created_at: string;
  updated_at: string;
  rounds: CandidateRound[];
}

interface CacheData {
  requisition: Requisition;
  candidates: Candidate[];
  timestamp: number;
}

type Tab = "active" | "archived";

function CandidateSkeleton() {
  return (
    <tr className="animate-pulse">
      <td className="px-4 py-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-secondary" />
          <div className="h-4 bg-secondary rounded w-32" />
        </div>
      </td>
      <td className="px-4 py-4"><div className="h-4 bg-secondary rounded w-48" /></td>
      <td className="px-4 py-4"><div className="h-4 bg-secondary rounded w-20" /></td>
      <td className="px-4 py-4"><div className="h-4 bg-secondary rounded w-24" /></td>
      <td className="px-4 py-4"><div className="h-8 bg-secondary rounded w-24 ml-auto" /></td>
    </tr>
  );
}

export default function CandidatesListPage() {
  const params = useParams();
  const router = useRouter();
  const requisitionId = params.id as string;

  const [requisition, setRequisition] = useState<Requisition | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [archivedCandidates, setArchivedCandidates] = useState<Candidate[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<Tab>("active");
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [actionCandidateId, setActionCandidateId] = useState<string | null>(null);
  const [showAddCandidateModal, setShowAddCandidateModal] = useState(false);
  const [newCandidateName, setNewCandidateName] = useState("");
  const [newCandidateEmail, setNewCandidateEmail] = useState("");
  const [addingCandidate, setAddingCandidate] = useState(false);
  const [addCandidateError, setAddCandidateError] = useState("");

  const getCacheKey = useCallback(() => `openrecruiting_req_candidates_${requisitionId}_cache`, [requisitionId]);

  const loadCachedData = useCallback(() => {
    try {
      const cached = sessionStorage.getItem(getCacheKey());
      if (cached) {
        const data: CacheData = JSON.parse(cached);
        if (Date.now() - data.timestamp < CACHE_DURATION) {
          return data;
        }
      }
    } catch {
      console.error("Error loading cached data");
    }
    return null;
  }, [getCacheKey]);

  const saveCachedData = useCallback((requisition: Requisition, candidates: Candidate[]) => {
    try {
      const data: CacheData = {
        requisition,
        candidates,
        timestamp: Date.now(),
      };
      sessionStorage.setItem(getCacheKey(), JSON.stringify(data));
    } catch {
      console.error("Error saving cached data");
    }
  }, [getCacheKey]);

  const fetchData = useCallback(async (showLoadingState: boolean = true, skipCache: boolean = false) => {
    if (!skipCache) {
      const cached = loadCachedData();
      if (cached) {
        setRequisition(cached.requisition);
        const active = cached.candidates.filter(c => c.status === "active");
        const archived = cached.candidates.filter(c => c.status !== "active");
        setCandidates(active);
        setArchivedCandidates(archived);
        setIsLoading(false);
        return;
      }
    }

    if (showLoadingState) setIsLoading(true);
    else setIsRefreshing(true);
    setError("");

    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        throw new Error("Not authenticated");
      }

      const [reqResponse, candidatesResponse] = await Promise.all([
        fetch(`${API_V2_URL}/api/v2/admin/requisitions/${requisitionId}`, {
          headers: {
            "Authorization": `Bearer ${session.access_token}`,
            "Content-Type": "application/json",
          },
        }),
        fetch(`${API_V2_URL}/api/v2/admin/requisitions/${requisitionId}/candidates`, {
          headers: {
            "Authorization": `Bearer ${session.access_token}`,
            "Content-Type": "application/json",
          },
        }),
      ]);

      if (!reqResponse.ok || !candidatesResponse.ok) {
        throw new Error("Failed to fetch data");
      }

      const reqData = await reqResponse.json();
      const candidatesData = await candidatesResponse.json();

      setRequisition(reqData);
      const allCandidates = candidatesData.candidates || [];
      const active = allCandidates.filter((c: Candidate) => c.status === "active");
      const archived = allCandidates.filter((c: Candidate) => c.status !== "active");
      setCandidates(active);
      setArchivedCandidates(archived);
      saveCachedData(reqData, allCandidates);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load data");
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [requisitionId, loadCachedData, saveCachedData]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleDeleteCandidate = async (candidateId: string) => {
    setActionCandidateId(candidateId);
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        throw new Error("Not authenticated");
      }

      const response = await fetch(`${API_V2_URL}/api/v2/admin/candidates/${candidateId}/status`, {
        method: "PUT",
        headers: {
          "Authorization": `Bearer ${session.access_token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ status: "withdrawn" }),
      });

      if (!response.ok) {
        throw new Error("Failed to archive candidate");
      }

      await fetchData(false, true);
      setDeleteConfirmId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to archive candidate");
    } finally {
      setActionCandidateId(null);
    }
  };

  const handleRestoreCandidate = async (candidateId: string) => {
    setActionCandidateId(candidateId);
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        throw new Error("Not authenticated");
      }

      const response = await fetch(`${API_V2_URL}/api/v2/admin/candidates/${candidateId}/status`, {
        method: "PUT",
        headers: {
          "Authorization": `Bearer ${session.access_token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ status: "active" }),
      });

      if (!response.ok) {
        throw new Error("Failed to restore candidate");
      }

      await fetchData(false, true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to restore candidate");
    } finally {
      setActionCandidateId(null);
    }
  };

  const handleAddCandidate = async (e: React.FormEvent) => {
    e.preventDefault();
    setAddingCandidate(true);
    setAddCandidateError("");

    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        throw new Error("Not authenticated");
      }

      const response = await fetch(`${API_V2_URL}/api/v2/admin/requisitions/${requisitionId}/candidates`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${session.access_token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ name: newCandidateName, email: newCandidateEmail }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(data?.detail || "Failed to add candidate");
      }

      setShowAddCandidateModal(false);
      setNewCandidateName("");
      setNewCandidateEmail("");
      await fetchData(false, true);
    } catch (err) {
      setAddCandidateError(err instanceof Error ? err.message : "Failed to add candidate");
    } finally {
      setAddingCandidate(false);
    }
  };

  const getStatusBadge = (status: string) => {
    const styles: Record<string, string> = {
      active: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
      hired: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
      rejected: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
      withdrawn: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400",
    };
    return styles[status] || styles.active;
  };

  const getVerdictBadge = (verdict: string | null) => {
    if (!verdict) return null;
    const styles: Record<string, { bg: string; text: string }> = {
      strong_hire: { bg: "bg-green-500/20", text: "Strong Hire" },
      hire: { bg: "bg-green-100 dark:bg-green-900/30", text: "Hire" },
      no_hire: { bg: "bg-red-100 dark:bg-red-900/30", text: "No Hire" },
      strong_no_hire: { bg: "bg-red-500/20", text: "Strong No Hire" },
    };
    const style = styles[verdict];
    return style ? (
      <span className={`px-2 py-1 text-xs rounded font-medium ${style.bg}`}>
        {style.text}
      </span>
    ) : null;
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  };

  const displayCandidates = activeTab === "active" ? candidates : archivedCandidates;

  return (
    <AuthGuard>
      <div id="candidates-list-page" className="min-h-screen bg-background">
        <AdminNav />

        <main id="candidates-main-content" className="max-w-7xl mx-auto px-6 py-8">
          <div id="candidates-back-nav" className="mb-6">
            <button
              id="candidates-back-btn"
              onClick={() => router.back()}
              className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              Back
            </button>
          </div>

          {error && (
            <div id="candidates-error-alert" className="mb-6 p-4 bg-destructive/10 border border-destructive/20 rounded-lg text-destructive flex items-center gap-2">
              <AlertTriangle className="w-5 h-5" />
              {error}
            </div>
          )}

          {isLoading ? (
            <div id="candidates-loading-skeleton" className="space-y-6">
              <div className="animate-pulse">
                <div className="h-8 bg-secondary rounded w-64 mb-2" />
                <div className="h-4 bg-secondary rounded w-48" />
              </div>
              <div className="bg-card border border-border rounded-xl overflow-hidden">
                <table className="w-full">
                  <tbody>
                    {[1, 2, 3].map(i => <CandidateSkeleton key={i} />)}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <>
              <div id="candidates-header-section" className="mb-8">
                <div className="flex items-center justify-between">
                  <h1 id="candidates-page-title" className="text-2xl font-bold">{requisition?.role_title || "Loading..."}</h1>
                  {activeTab === "active" && (
                    <button
                      id="add-candidate-btn"
                      onClick={() => setShowAddCandidateModal(true)}
                      className="flex items-center gap-2 px-4 py-2 text-sm font-medium bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
                    >
                      <Plus className="w-4 h-4" />
                      Add Candidate
                    </button>
                  )}
                </div>
                <div className="flex items-center gap-4 mt-2 text-sm text-muted-foreground">
                  {requisition?.role_location && (
                    <span className="flex items-center gap-1">
                      <MapPin className="w-4 h-4" />
                      {requisition.role_location}
                    </span>
                  )}
                  {requisition?.experience_display && (
                    <span className="flex items-center gap-1">
                      <Briefcase className="w-4 h-4" />
                      {requisition.experience_display}
                    </span>
                  )}
                  <span className="flex items-center gap-1">
                    <Users className="w-4 h-4" />
                    {candidates.length} Active Candidate{candidates.length !== 1 ? "s" : ""}
                  </span>
                </div>
              </div>

              <div id="candidates-tabs-section" className="flex items-center gap-2 mb-6 border-b border-border">
                <button
                  id="candidates-tab-active"
                  onClick={() => setActiveTab("active")}
                  className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === "active"
                      ? "border-primary text-primary"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  }`}
                >
                  Active ({candidates.length})
                </button>
                <button
                  id="candidates-tab-archived"
                  onClick={() => setActiveTab("archived")}
                  className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === "archived"
                      ? "border-primary text-primary"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  }`}
                >
                  Archived ({archivedCandidates.length})
                </button>
                {isRefreshing && (
                  <Loader2 className="w-4 h-4 animate-spin ml-auto text-muted-foreground" />
                )}
              </div>

              <div id="candidates-table-card" className="bg-card border border-border rounded-xl overflow-hidden">
                <table id="candidates-table" className="w-full">
                  <thead>
                    <tr className="border-b border-border bg-secondary/30">
                      <th id="col-candidate-name" className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">Name</th>
                      <th id="col-candidate-email" className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">Email</th>
                      <th id="col-candidate-status" className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">Status</th>
                      <th id="col-candidate-progress" className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">Progress</th>
                      <th id="col-candidate-actions" className="px-4 py-3 text-right text-sm font-medium text-muted-foreground">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {displayCandidates.map((candidate) => {
                      const completedRounds = candidate.rounds.filter(r => r.status === "completed").length;
                      const totalRounds = candidate.rounds.length;

                      return (
                        <tr key={candidate.id} id={`candidate-row-${candidate.id}`} className="border-b border-border last:border-0 hover:bg-secondary/20">
                          <td id={`candidate-name-${candidate.id}`} className="px-4 py-4">
                            <div className="flex items-center gap-3">
                              <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center text-primary font-medium">
                                {candidate.name.charAt(0).toUpperCase()}
                              </div>
                              <span className="font-medium">{candidate.name}</span>
                            </div>
                          </td>
                          <td id={`candidate-email-${candidate.id}`} className="px-4 py-4">
                            <span className="text-muted-foreground">{candidate.email}</span>
                          </td>
                          <td id={`candidate-status-${candidate.id}`} className="px-4 py-4">
                            <span className={`px-2 py-1 text-xs rounded font-medium ${getStatusBadge(candidate.status)}`}>
                              {candidate.status.charAt(0).toUpperCase() + candidate.status.slice(1)}
                            </span>
                            {candidate.final_verdict && (
                              <span className="ml-2">
                                {getVerdictBadge(candidate.final_verdict)}
                              </span>
                            )}
                          </td>
                          <td id={`candidate-progress-${candidate.id}`} className="px-4 py-4">
                            <div className="flex items-center gap-2">
                              {candidate.rounds.map((round, idx) => (
                                <div
                                  key={round.id}
                                  id={`candidate-round-dot-${candidate.id}-${round.id}`}
                                  className={`w-6 h-6 rounded-full flex items-center justify-center text-xs ${
                                    round.status === "completed"
                                      ? "bg-primary text-primary-foreground"
                                      : round.status === "scheduled"
                                      ? "bg-primary/20 border-2 border-primary"
                                      : round.status === "in_progress"
                                      ? "bg-yellow-500/20 border-2 border-yellow-500"
                                      : "bg-secondary border border-border"
                                  }`}
                                  title={`${round.round_name} - ${round.status}`}
                                >
                                  {round.status === "completed" ? (
                                    <Check className="w-3 h-3" />
                                  ) : round.status === "scheduled" ? (
                                    <Calendar className="w-3 h-3" />
                                  ) : round.status === "in_progress" ? (
                                    <Play className="w-3 h-3" />
                                  ) : (
                                    idx + 1
                                  )}
                                </div>
                              ))}
                              <span className="text-xs text-muted-foreground ml-1">
                                {completedRounds}/{totalRounds}
                              </span>
                            </div>
                          </td>
                          <td id={`candidate-actions-${candidate.id}`} className="px-4 py-4">
                            <div className="flex items-center justify-end gap-2">
                              {activeTab === "active" ? (
                                <>
                                  <Link
                                    id={`candidate-edit-scorecard-${candidate.id}`}
                                    href={`/requisitions/${requisitionId}/candidates/${candidate.id}/scorecard`}
                                    className="flex items-center gap-1 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
                                  >
                                    <Edit className="w-4 h-4" />
                                    Edit Scorecard
                                  </Link>
                                  {deleteConfirmId === candidate.id ? (
                                    <div className="flex items-center gap-1">
                                      <button
                                        id={`candidate-confirm-delete-${candidate.id}`}
                                        onClick={() => handleDeleteCandidate(candidate.id)}
                                        disabled={actionCandidateId === candidate.id}
                                        className="px-2 py-1 text-xs bg-destructive text-destructive-foreground rounded hover:bg-destructive/90 disabled:opacity-50"
                                      >
                                        {actionCandidateId === candidate.id ? (
                                          <Loader2 className="w-3 h-3 animate-spin" />
                                        ) : (
                                          "Confirm"
                                        )}
                                      </button>
                                      <button
                                        id={`candidate-cancel-delete-${candidate.id}`}
                                        onClick={() => setDeleteConfirmId(null)}
                                        className="px-2 py-1 text-xs border border-border rounded hover:bg-secondary"
                                      >
                                        Cancel
                                      </button>
                                    </div>
                                  ) : (
                                    <button
                                      id={`candidate-delete-btn-${candidate.id}`}
                                      onClick={() => setDeleteConfirmId(candidate.id)}
                                      className="p-1.5 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded transition-colors"
                                      title="Archive candidate"
                                    >
                                      <Trash2 className="w-4 h-4" />
                                    </button>
                                  )}
                                </>
                              ) : (
                                <button
                                  id={`candidate-restore-btn-${candidate.id}`}
                                  onClick={() => handleRestoreCandidate(candidate.id)}
                                  disabled={actionCandidateId === candidate.id}
                                  className="flex items-center gap-1 px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-secondary transition-colors disabled:opacity-50"
                                >
                                  {actionCandidateId === candidate.id ? (
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                  ) : (
                                    <RotateCcw className="w-4 h-4" />
                                  )}
                                  Restore
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                    {displayCandidates.length === 0 && (
                      <tr>
                        <td colSpan={5} className="px-4 py-12 text-center text-muted-foreground">
                          {activeTab === "active"
                            ? "No active candidates for this requisition"
                            : "No archived candidates"}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
          {showAddCandidateModal && (
            <div id="add-candidate-modal-overlay" className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => !addingCandidate && setShowAddCandidateModal(false)}>
              <div id="add-candidate-modal" className="bg-card border border-border rounded-xl shadow-lg w-full max-w-md mx-4 p-6" onClick={(e) => e.stopPropagation()}>
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-semibold">Add Candidate</h2>
                  <button
                    id="add-candidate-modal-close"
                    onClick={() => { setShowAddCandidateModal(false); setAddCandidateError(""); }}
                    disabled={addingCandidate}
                    className="p-1 text-muted-foreground hover:text-foreground rounded transition-colors disabled:opacity-50"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </div>

                <form onSubmit={handleAddCandidate} className="space-y-4">
                  <div>
                    <label htmlFor="candidate-name" className="block text-sm font-medium mb-1">Name</label>
                    <input
                      id="candidate-name"
                      type="text"
                      required
                      value={newCandidateName}
                      onChange={(e) => setNewCandidateName(e.target.value)}
                      placeholder="Full name"
                      className="w-full px-3 py-2 text-sm border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                    />
                  </div>
                  <div>
                    <label htmlFor="candidate-email" className="block text-sm font-medium mb-1">Email</label>
                    <input
                      id="candidate-email"
                      type="email"
                      required
                      value={newCandidateEmail}
                      onChange={(e) => setNewCandidateEmail(e.target.value)}
                      placeholder="candidate@example.com"
                      className="w-full px-3 py-2 text-sm border border-border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                    />
                  </div>

                  {addCandidateError && (
                    <div id="add-candidate-error" className="p-3 text-sm bg-destructive/10 border border-destructive/20 rounded-lg text-destructive flex items-center gap-2">
                      <AlertTriangle className="w-4 h-4 shrink-0" />
                      {addCandidateError}
                    </div>
                  )}

                  <div className="flex items-center justify-end gap-2 pt-2">
                    <button
                      id="add-candidate-cancel"
                      type="button"
                      onClick={() => { setShowAddCandidateModal(false); setAddCandidateError(""); }}
                      disabled={addingCandidate}
                      className="px-4 py-2 text-sm border border-border rounded-lg hover:bg-secondary transition-colors disabled:opacity-50"
                    >
                      Cancel
                    </button>
                    <button
                      id="add-candidate-submit"
                      type="submit"
                      disabled={addingCandidate}
                      className="flex items-center gap-2 px-4 py-2 text-sm font-medium bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
                    >
                      {addingCandidate && <Loader2 className="w-4 h-4 animate-spin" />}
                      {addingCandidate ? "Adding..." : "Add Candidate"}
                    </button>
                  </div>
                </form>
              </div>
            </div>
          )}
        </main>
      </div>
    </AuthGuard>
  );
}
