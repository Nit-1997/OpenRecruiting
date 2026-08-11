"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { AuthGuard } from "@/components/auth-guard";
import { AdminNav } from "@/components/admin-nav";
import { BlogPostForm, BlogFormData } from "@/components/blog-post-form";
import { createClient } from "@/lib/supabase/client";
import { getRuntimeConfig } from "@/lib/runtime-config";

// V2 backend base — these admin endpoints are ported to /api/v2/admin.
const API_V2_URL = getRuntimeConfig().apiV2Url || "http://localhost:8004";

export default function NewBlogPostPage() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [error, setError] = useState("");

  const loadToken = useCallback(async () => {
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) {
      router.push("/login");
      return;
    }
    setToken(session.access_token);
  }, [router]);

  useEffect(() => { loadToken(); }, [loadToken]);

  const handleSubmit = async (data: BlogFormData) => {
    setError("");
    const response = await fetch(`${API_V2_URL}/api/v2/admin/blog-posts`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
    });
    if (!response.ok) {
      const err = await response.json().catch(() => null);
      throw new Error(err?.detail || "Failed to create post");
    }
    router.push("/blog");
  };

  if (!token) return null;

  return (
    <AuthGuard>
      <div id="blog-new-page" className="min-h-screen bg-secondary/30">
        <AdminNav />
        <main id="blog-new-main" className="max-w-4xl mx-auto p-6">
          <button id="blog-new-back" onClick={() => router.push("/blog")} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors mb-6">
            <ArrowLeft className="w-4 h-4" />
            Back to Blog Posts
          </button>
          <h1 id="blog-new-title" className="text-3xl font-bold mb-8">New Blog Post</h1>
          {error && (
            <div id="blog-new-error" className="bg-destructive/10 text-destructive border border-destructive/20 rounded-lg p-4 mb-6">{error}</div>
          )}
          <BlogPostForm onSubmit={handleSubmit} submitLabel="Create Post" token={token} mode="create" />
        </main>
      </div>
    </AuthGuard>
  );
}
