"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Plus,
  Search,
  ClipboardList,
  Clock,
  Edit,
  Trash2,
  Eye,
  Loader2,
  FileJson,
  CheckCircle,
  AlertCircle,
} from "lucide-react";
import { AuthGuard } from "@/components/auth-guard";
import { AdminNav } from "@/components/admin-nav";
import { createClient } from "@/lib/supabase/client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
// V2 backend base — assessment-templates admin endpoints are ported to /api/v2/admin.
const API_V2_URL = process.env.NEXT_PUBLIC_API_V2_URL || "http://localhost:8004";

interface AssessmentTemplate {
  id: string;
  title: string;
  description: string | null;
  role_seniority: string | null;
  tools_enabled: string[];
  time_limit_minutes: number;
  status: "draft" | "published" | "archived";
  version: string;
  created_at: string;
  updated_at: string;
}

function TemplateSkeleton() {
  return (
    <div id="template-skeleton" className="bg-card rounded-xl border border-border p-6 animate-pulse">
      <div className="flex items-start justify-between mb-4">
        <div className="w-10 h-10 rounded-lg bg-secondary" />
        <div className="w-16 h-6 bg-secondary rounded-full" />
      </div>
      <div className="h-5 bg-secondary rounded w-3/4 mb-2" />
      <div className="h-4 bg-secondary rounded w-1/2 mb-4" />
      <div className="flex gap-2 mb-4">
        <div className="h-6 w-20 bg-secondary rounded-full" />
        <div className="h-6 w-24 bg-secondary rounded-full" />
      </div>
      <div className="flex justify-end pt-4 border-t border-border gap-2">
        <div className="h-8 w-16 bg-secondary rounded" />
        <div className="h-8 w-16 bg-secondary rounded" />
      </div>
    </div>
  );
}

export default function AssessmentsPage() {
  const router = useRouter();
  const [templates, setTemplates] = useState<AssessmentTemplate[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "draft" | "published" | "archived">("all");
  const [deleteConfirm, setDeleteConfirm] = useState<AssessmentTemplate | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const fetchTemplates = useCallback(async () => {
    try {
      setIsLoading(true);
      setError("");
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) {
        router.push("/login");
        return;
      }

      const response = await fetch(`${API_V2_URL}/api/v2/admin/assessment-templates`, {
        headers: { Authorization: `Bearer ${session.access_token}` },
      });

      if (!response.ok) {
        console.warn("Assessment templates API not available yet");
        setTemplates([]);
        return;
      }

      const data = await response.json();
      setTemplates(data.templates || []);
    } catch (err) {
      console.warn("Error fetching templates (API may not be available):", err);
      setTemplates([]);
    } finally {
      setIsLoading(false);
    }
  }, [router]);

  useEffect(() => {
    fetchTemplates();
  }, [fetchTemplates]);

  const handleDelete = async (template: AssessmentTemplate) => {
    try {
      setActionLoading(template.id);
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();

      if (!session?.access_token) return;

      const response = await fetch(`${API_V2_URL}/api/v2/admin/assessment-templates/${template.id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${session.access_token}` },
      });

      if (response.ok) {
        setTemplates((prev) => prev.filter((t) => t.id !== template.id));
        setDeleteConfirm(null);
      }
    } catch (err) {
      console.error("Error deleting template:", err);
    } finally {
      setActionLoading(null);
    }
  };

  const filteredTemplates = templates.filter((template) => {
    const matchesSearch =
      template.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      template.description?.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesStatus = statusFilter === "all" || template.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "published":
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400">
            <CheckCircle className="w-3 h-3" />
            Published
          </span>
        );
      case "draft":
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400">
            <Edit className="w-3 h-3" />
            Draft
          </span>
        );
      case "archived":
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
            <AlertCircle className="w-3 h-3" />
            Archived
          </span>
        );
      default:
        return null;
    }
  };

  return (
    <AuthGuard>
      <div id="assessments-page" className="min-h-screen bg-secondary/30">
        <AdminNav />

        <main id="assessments-main" className="p-6">
          <div id="assessments-header" className="flex items-center justify-between mb-8">
            <div>
              <h1 id="assessments-title" className="text-3xl font-bold flex items-center gap-3">
                <ClipboardList className="w-8 h-8 text-primary" />
                Assessment Templates
              </h1>
              <p id="assessments-subtitle" className="text-muted-foreground mt-1">
                Create and manage assessment templates with task definitions and evaluation rubrics
              </p>
            </div>
            <Link
              href="/assessments/new"
              id="new-template-btn"
              className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
            >
              <Plus className="w-4 h-4" />
              New Template
            </Link>
          </div>

          {/* Filters */}
          <div id="assessments-filters" className="flex items-center gap-4 mb-6">
            <div className="relative flex-1 max-w-md">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <input
                id="assessments-search"
                type="text"
                placeholder="Search templates..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-10 pr-4 py-2 bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
            </div>
            <div id="status-filter" className="flex items-center gap-1 bg-card border border-border rounded-lg p-1">
              {(["all", "draft", "published", "archived"] as const).map((status) => (
                <button
                  key={status}
                  onClick={() => setStatusFilter(status)}
                  className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                    statusFilter === status
                      ? "bg-primary text-primary-foreground"
                      : "hover:bg-secondary"
                  }`}
                >
                  {status.charAt(0).toUpperCase() + status.slice(1)}
                </button>
              ))}
            </div>
          </div>

          {/* Error State */}
          {error && (
            <div id="assessments-error" className="bg-destructive/10 text-destructive border border-destructive/20 rounded-lg p-4 mb-6">
              {error}
            </div>
          )}

          {/* Templates Grid */}
          <div id="templates-grid" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {isLoading ? (
              <>
                <TemplateSkeleton />
                <TemplateSkeleton />
                <TemplateSkeleton />
              </>
            ) : filteredTemplates.length === 0 ? (
              <div id="templates-empty" className="col-span-full text-center py-12">
                <ClipboardList className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
                <h3 className="text-lg font-medium mb-2">No templates found</h3>
                <p className="text-muted-foreground mb-4">
                  {searchQuery ? "Try adjusting your search" : "Create your first assessment template"}
                </p>
                {!searchQuery && (
                  <Link
                    href="/assessments/new"
                    className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90"
                  >
                    <Plus className="w-4 h-4" />
                    Create Template
                  </Link>
                )}
              </div>
            ) : (
              filteredTemplates.map((template) => (
                <div
                  key={template.id}
                  id={`template-${template.id}`}
                  className="bg-card rounded-xl border border-border p-6 hover:shadow-lg transition-shadow"
                >
                  <div className="flex items-start justify-between mb-4">
                    <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                      <FileJson className="w-5 h-5 text-primary" />
                    </div>
                    {getStatusBadge(template.status)}
                  </div>

                  <h3 className="font-semibold text-lg mb-1 line-clamp-1">{template.title}</h3>
                  <p className="text-sm text-muted-foreground mb-4 line-clamp-2">
                    {template.description || "No description"}
                  </p>

                  <div className="flex flex-wrap gap-2 mb-4">
                    {template.role_seniority && (
                      <span className="px-2 py-1 bg-secondary text-xs rounded-full">
                        {template.role_seniority}
                      </span>
                    )}
                    <span className="px-2 py-1 bg-secondary text-xs rounded-full flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {template.time_limit_minutes} min
                    </span>
                    <span className="px-2 py-1 bg-secondary text-xs rounded-full">
                      v{template.version}
                    </span>
                  </div>

                  <div className="flex items-center justify-between pt-4 border-t border-border">
                    <span className="text-xs text-muted-foreground">
                      Updated {new Date(template.updated_at).toLocaleDateString()}
                    </span>
                    <div className="flex items-center gap-2">
                      <Link
                        href={`/assessments/${template.id}`}
                        className="p-2 hover:bg-secondary rounded-lg transition-colors"
                        title="Edit"
                      >
                        <Edit className="w-4 h-4" />
                      </Link>
                      <button
                        onClick={() => setDeleteConfirm(template)}
                        className="p-2 hover:bg-destructive/10 text-destructive rounded-lg transition-colors"
                        title="Delete"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </main>

        {/* Delete Confirmation Modal */}
        {deleteConfirm && (
          <div id="delete-modal" className="fixed inset-0 z-50 flex items-center justify-center">
            <div className="absolute inset-0 bg-black/50" onClick={() => setDeleteConfirm(null)} />
            <div className="relative bg-card rounded-xl shadow-xl max-w-md w-full mx-4 p-6">
              <h3 className="text-lg font-semibold mb-2">Delete Template?</h3>
              <p className="text-muted-foreground mb-4">
                Are you sure you want to delete &ldquo;{deleteConfirm.title}&rdquo;? This action cannot be undone.
              </p>
              <div className="flex justify-end gap-3">
                <button
                  onClick={() => setDeleteConfirm(null)}
                  className="px-4 py-2 rounded-lg hover:bg-secondary transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={() => handleDelete(deleteConfirm)}
                  disabled={actionLoading === deleteConfirm.id}
                  className="px-4 py-2 bg-destructive text-destructive-foreground rounded-lg hover:bg-destructive/90 disabled:opacity-50 flex items-center gap-2"
                >
                  {actionLoading === deleteConfirm.id ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Deleting...
                    </>
                  ) : (
                    "Delete"
                  )}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </AuthGuard>
  );
}
