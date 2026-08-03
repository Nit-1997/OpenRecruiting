"use client";

import { useState, useEffect, useCallback, use } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Loader2 } from "lucide-react";
import { AuthGuard } from "@/components/auth-guard";
import { AdminNav } from "@/components/admin-nav";
import { BlogPostForm, BlogFormData } from "@/components/blog-post-form";
import { createClient } from "@/lib/supabase/client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
// V2 backend base — these admin endpoints are ported to /api/v2/admin.
const API_V2_URL = process.env.NEXT_PUBLIC_API_V2_URL || "http://localhost:8004";

export default function EditBlogPostPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const router = useRouter();
  const [token, setToken] = useState("");
  const [post, setPost] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadData = useCallback(async () => {
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) {
      router.push("/login");
      return;
    }
    setToken(session.access_token);

    const response = await fetch(`${API_V2_URL}/api/v2/admin/blog-posts/${slug}`, {
      headers: { Authorization: `Bearer ${session.access_token}` },
    });
    if (!response.ok) {
      setError("Failed to load post");
      setLoading(false);
      return;
    }
    const data = await response.json();
    setPost(data);
    setLoading(false);
  }, [slug, router]);

  useEffect(() => { loadData(); }, [loadData]);

  const handleSubmit = async (data: BlogFormData) => {
    setError("");
    const response = await fetch(`${API_V2_URL}/api/v2/admin/blog-posts/${slug}`, {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
    });
    if (!response.ok) {
      const err = await response.json().catch(() => null);
      throw new Error(err?.detail || "Failed to update post");
    }
    router.push("/blog");
  };

  return (
    <AuthGuard>
      <div id="blog-edit-page" className="min-h-screen bg-secondary/30">
        <AdminNav />
        <main id="blog-edit-main" className="max-w-4xl mx-auto p-6">
          <button id="blog-edit-back" onClick={() => router.push("/blog")} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors mb-6">
            <ArrowLeft className="w-4 h-4" />
            Back to Blog Posts
          </button>
          <h1 id="blog-edit-title" className="text-3xl font-bold mb-8">Edit Blog Post</h1>
          {error && (
            <div id="blog-edit-error" className="bg-destructive/10 text-destructive border border-destructive/20 rounded-lg p-4 mb-6">{error}</div>
          )}
          {loading ? (
            <div id="blog-edit-loading" className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="w-5 h-5 animate-spin" />
              Loading post...
            </div>
          ) : post ? (
            <BlogPostForm
              initialData={{
                title: post.title as string,
                slug: post.slug as string,
                excerpt: post.excerpt as string,
                content: post.content as string,
                thumbnail_url: (post.thumbnail_url as string) || undefined,
                hero_image_url: (post.hero_image_url as string) || undefined,
                author_name: post.author_name as string,
                author_avatar: (post.author_avatar as string) || undefined,
                tags: (post.tags as string[]) || [],
                status: post.status as string,
              }}
              onSubmit={handleSubmit}
              submitLabel="Update Post"
              token={token}
              mode="edit"
            />
          ) : null}
        </main>
      </div>
    </AuthGuard>
  );
}
