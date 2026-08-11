"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { FileText, Plus, Pencil, Trash2, Loader2, X, AlertTriangle } from "lucide-react";
import { AuthGuard } from "@/components/auth-guard";
import { AdminNav } from "@/components/admin-nav";
import { createClient } from "@/lib/supabase/client";
import { getRuntimeConfig } from "@/lib/runtime-config";

// V2 backend base — these admin endpoints are ported to /api/v2/admin.
const API_V2_URL = getRuntimeConfig().apiV2Url || "http://localhost:8004";

interface BlogPost {
  id: string;
  slug: string;
  title: string;
  excerpt: string;
  status: string;
  author_name: string;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export default function BlogListPage() {
  const router = useRouter();
  const [posts, setPosts] = useState<BlogPost[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState<BlogPost | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const getToken = useCallback(async () => {
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) {
      router.push("/login");
      return null;
    }
    return session.access_token;
  }, [router]);

  const fetchPosts = useCallback(async () => {
    try {
      const token = await getToken();
      if (!token) return;
      const response = await fetch(`${API_V2_URL}/api/v2/admin/blog-posts?page=1&page_size=100`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) throw new Error("Failed to fetch posts");
      const data = await response.json();
      setPosts(data.posts || []);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setIsLoading(false);
    }
  }, [getToken]);

  useEffect(() => { fetchPosts(); }, [fetchPosts]);

  const handleDelete = async () => {
    if (!deleteConfirm) return;
    setActionLoading(deleteConfirm.id);
    try {
      const token = await getToken();
      if (!token) return;
      const response = await fetch(`${API_V2_URL}/api/v2/admin/blog-posts/${deleteConfirm.slug}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) throw new Error("Failed to delete post");
      setPosts(posts.filter((p) => p.id !== deleteConfirm.id));
      setDeleteConfirm(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete");
    } finally {
      setActionLoading(null);
    }
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  };

  return (
    <AuthGuard>
      {deleteConfirm && (
        <div id="blog-delete-overlay" className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 animate-in fade-in duration-200">
          <div id="blog-delete-modal" className="bg-card rounded-xl border border-border shadow-xl max-w-md w-full p-6 animate-in zoom-in-95 duration-200">
            <div className="flex items-start gap-4">
              <div id="blog-delete-icon" className="w-10 h-10 rounded-full bg-destructive/10 flex items-center justify-center flex-shrink-0">
                <AlertTriangle className="w-5 h-5 text-destructive" />
              </div>
              <div className="flex-1">
                <h3 id="blog-delete-title" className="text-lg font-semibold mb-2">Delete Post</h3>
                <p id="blog-delete-description" className="text-muted-foreground text-sm mb-4">
                  Are you sure you want to delete <span className="font-medium text-foreground">{deleteConfirm.title}</span>?
                </p>
                <div className="flex gap-3 justify-end">
                  <button id="blog-delete-cancel" onClick={() => setDeleteConfirm(null)} disabled={actionLoading === deleteConfirm.id} className="px-4 py-2 border border-border rounded-lg hover:bg-secondary transition-colors disabled:opacity-50">Cancel</button>
                  <button id="blog-delete-confirm" onClick={handleDelete} disabled={actionLoading === deleteConfirm.id} className="px-4 py-2 bg-destructive text-destructive-foreground rounded-lg hover:bg-destructive/90 transition-colors disabled:opacity-50 flex items-center gap-2">
                    {actionLoading === deleteConfirm.id && <Loader2 className="w-4 h-4 animate-spin" />}
                    {actionLoading === deleteConfirm.id ? "Deleting..." : "Delete"}
                  </button>
                </div>
              </div>
              <button id="blog-delete-close" onClick={() => setDeleteConfirm(null)} className="text-muted-foreground hover:text-foreground transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>
      )}

      <div id="blog-page" className="min-h-screen bg-secondary/30">
        <AdminNav />
        <main id="blog-main" className="max-w-5xl mx-auto p-6">
          <div id="blog-header" className="flex items-center justify-between mb-8">
            <div>
              <h1 id="blog-title" className="text-3xl font-bold flex items-center gap-3">
                <FileText className="w-8 h-8 text-primary" />
                Blog Posts
              </h1>
              <p id="blog-subtitle" className="text-muted-foreground mt-1">Manage blog posts for the blog.</p>
            </div>
            <button id="blog-create-btn" onClick={() => router.push("/blog/new")} className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors">
              <Plus className="w-4 h-4" />
              New Post
            </button>
          </div>

          {error && (
            <div id="blog-error" className="bg-destructive/10 text-destructive border border-destructive/20 rounded-lg p-4 mb-6">
              {error}
              <button id="blog-error-dismiss" onClick={() => setError("")} className="ml-4 underline text-sm">Dismiss</button>
            </div>
          )}

          {isLoading ? (
            <div id="blog-skeleton" className="bg-card rounded-xl border border-border animate-pulse">
              {[1, 2, 3].map((i) => (
                <div key={i} id={`blog-skeleton-row-${i}`} className="flex items-center gap-4 px-6 py-4 border-b border-border last:border-b-0">
                  <div className="h-4 bg-secondary rounded w-48" />
                  <div className="h-6 bg-secondary rounded-full w-20" />
                  <div className="h-4 bg-secondary rounded w-24" />
                  <div className="h-4 bg-secondary rounded w-20 ml-auto" />
                </div>
              ))}
            </div>
          ) : posts.length === 0 ? (
            <div id="blog-empty" className="bg-card rounded-xl border border-border p-12 text-center">
              <FileText className="w-16 h-16 mx-auto mb-4 text-muted-foreground opacity-50" />
              <h2 id="blog-empty-title" className="text-xl font-semibold mb-2">No blog posts yet</h2>
              <p id="blog-empty-description" className="text-muted-foreground mb-6">Create your first blog post to get started.</p>
              <button id="blog-empty-create" onClick={() => router.push("/blog/new")} className="inline-flex items-center gap-2 px-6 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors">
                <Plus className="w-4 h-4" />
                New Post
              </button>
            </div>
          ) : (
            <div id="blog-table-wrapper" className="bg-card rounded-xl border border-border overflow-hidden">
              <table id="blog-table" className="w-full">
                <thead id="blog-table-head">
                  <tr className="border-b border-border bg-secondary/30">
                    <th id="blog-th-title" className="text-left px-6 py-3 text-sm font-medium text-muted-foreground">Title</th>
                    <th id="blog-th-status" className="text-left px-6 py-3 text-sm font-medium text-muted-foreground">Status</th>
                    <th id="blog-th-author" className="text-left px-6 py-3 text-sm font-medium text-muted-foreground">Author</th>
                    <th id="blog-th-created" className="text-left px-6 py-3 text-sm font-medium text-muted-foreground">Created</th>
                    <th id="blog-th-actions" className="text-right px-6 py-3 text-sm font-medium text-muted-foreground">Actions</th>
                  </tr>
                </thead>
                <tbody id="blog-table-body">
                  {posts.map((post) => (
                    <tr key={post.id} id={`blog-row-${post.id}`} className="border-b border-border last:border-b-0 hover:bg-secondary/20 transition-colors">
                      <td id={`blog-title-${post.id}`} className="px-6 py-4">
                        <div className="font-medium text-sm">{post.title}</div>
                        <div className="text-xs text-muted-foreground mt-0.5">/{post.slug}</div>
                      </td>
                      <td id={`blog-status-${post.id}`} className="px-6 py-4">
                        <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${
                          post.status === "published"
                            ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400"
                            : "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
                        }`}>
                          {post.status === "published" ? "Published" : "Draft"}
                        </span>
                      </td>
                      <td id={`blog-author-${post.id}`} className="px-6 py-4 text-sm text-muted-foreground">{post.author_name}</td>
                      <td id={`blog-created-${post.id}`} className="px-6 py-4 text-sm text-muted-foreground">{formatDate(post.created_at)}</td>
                      <td id={`blog-actions-${post.id}`} className="px-6 py-4">
                        <div className="flex items-center justify-end gap-1">
                          <button id={`blog-edit-${post.id}`} onClick={() => router.push(`/blog/edit/${post.slug}`)} className="p-2 hover:bg-secondary rounded-lg transition-colors" title="Edit">
                            <Pencil className="w-4 h-4" />
                          </button>
                          <button id={`blog-delete-${post.id}`} onClick={() => setDeleteConfirm(post)} className="p-2 hover:bg-destructive/10 text-destructive rounded-lg transition-colors" title="Delete">
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </main>
      </div>
    </AuthGuard>
  );
}
