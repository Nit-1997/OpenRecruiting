"use client";

import { useState, useRef, useCallback } from "react";
import { RichEditor } from "@/components/rich-editor";
import { ImageIcon, X, Loader2 } from "lucide-react";
import { getRuntimeConfig } from "@/lib/runtime-config";

// V2 backend base — these admin endpoints are ported to /api/v2/admin.
const API_V2_URL = getRuntimeConfig().apiV2Url || "http://localhost:8004";

function slugify(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

export interface BlogFormData {
  title: string;
  slug: string;
  excerpt: string;
  content: string;
  thumbnail_url?: string;
  hero_image_url?: string;
  author_name: string;
  author_avatar?: string;
  tags: string[];
  status: string;
}

interface BlogPostFormProps {
  initialData?: Partial<BlogFormData>;
  onSubmit: (data: BlogFormData) => Promise<void>;
  submitLabel: string;
  token: string;
  mode: "create" | "edit";
}

export function BlogPostForm({ initialData, onSubmit, submitLabel, token, mode }: BlogPostFormProps) {
  const [title, setTitle] = useState(initialData?.title ?? "");
  const [slug, setSlug] = useState(initialData?.slug ?? "");
  const [excerpt, setExcerpt] = useState(initialData?.excerpt ?? "");
  const [content, setContent] = useState(initialData?.content ?? "");
  const [thumbnailUrl, setThumbnailUrl] = useState(initialData?.thumbnail_url ?? "");
  const [heroImageUrl, setHeroImageUrl] = useState(initialData?.hero_image_url ?? "");
  const [authorName, setAuthorName] = useState(initialData?.author_name ?? "");
  const [authorAvatar, setAuthorAvatar] = useState(initialData?.author_avatar ?? "");
  const [tags, setTags] = useState(initialData?.tags?.join(", ") ?? "");
  const [status, setStatus] = useState(initialData?.status ?? "draft");
  const [slugManuallyEdited, setSlugManuallyEdited] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [thumbnailUploading, setThumbnailUploading] = useState(false);
  const [heroImageUploading, setHeroImageUploading] = useState(false);
  const [avatarUploading, setAvatarUploading] = useState(false);
  const thumbnailInputRef = useRef<HTMLInputElement>(null);
  const heroImageInputRef = useRef<HTMLInputElement>(null);
  const avatarInputRef = useRef<HTMLInputElement>(null);

  function handleTitleChange(value: string) {
    setTitle(value);
    if (!slugManuallyEdited) {
      setSlug(slugify(value));
    }
  }

  const uploadFile = useCallback(async (file: File): Promise<string> => {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`${API_V2_URL}/api/v2/admin/blog-posts/upload-image`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => null);
      throw new Error(err?.detail || "Upload failed");
    }
    const { url } = await res.json();
    return url;
  }, [token]);

  const uploadThumbnail = useCallback(async (file: File) => {
    setThumbnailUploading(true);
    try {
      const url = await uploadFile(file);
      setThumbnailUrl(url);
    } catch {
      alert("Thumbnail upload failed");
    } finally {
      setThumbnailUploading(false);
    }
  }, [uploadFile]);

  const uploadAvatar = useCallback(async (file: File) => {
    setAvatarUploading(true);
    try {
      const url = await uploadFile(file);
      setAuthorAvatar(url);
    } catch {
      alert("Avatar upload failed");
    } finally {
      setAvatarUploading(false);
    }
  }, [uploadFile]);

  const uploadHeroImage = useCallback(async (file: File) => {
    setHeroImageUploading(true);
    try {
      const url = await uploadFile(file);
      setHeroImageUrl(url);
    } catch {
      alert("Hero image upload failed");
    } finally {
      setHeroImageUploading(false);
    }
  }, [uploadFile]);

  function handleHeroImageDrop(e: React.DragEvent) {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith("image/")) {
      uploadHeroImage(file);
    }
  }

  function handleThumbnailDrop(e: React.DragEvent) {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith("image/")) {
      uploadThumbnail(file);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await onSubmit({
        title,
        slug: slug || slugify(title),
        excerpt,
        content,
        thumbnail_url: thumbnailUrl || undefined,
        hero_image_url: heroImageUrl || undefined,
        author_name: authorName || "OpenRecruiting Team",
        author_avatar: authorAvatar || undefined,
        tags: tags ? tags.split(",").map((t) => t.trim()).filter(Boolean) : [],
        status,
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form id={`blog-form-${mode}`} onSubmit={handleSubmit} className="space-y-6 max-w-4xl">
      <div className="space-y-2">
        <label id="blog-form-title-label" htmlFor="blog-form-title" className="block text-sm font-medium">Title</label>
        <input
          id="blog-form-title"
          type="text"
          value={title}
          onChange={(e) => handleTitleChange(e.target.value)}
          placeholder="Post title"
          required
          className="w-full px-3 py-2 border border-border rounded-lg bg-card focus:outline-none focus:ring-2 focus:ring-primary/50"
        />
      </div>

      <div className="space-y-2">
        <label id="blog-form-slug-label" htmlFor="blog-form-slug" className="block text-sm font-medium">Slug</label>
        <input
          id="blog-form-slug"
          type="text"
          value={slug}
          onChange={(e) => { setSlug(e.target.value); setSlugManuallyEdited(true); }}
          placeholder="post-url-slug"
          required
          className="w-full px-3 py-2 border border-border rounded-lg bg-card focus:outline-none focus:ring-2 focus:ring-primary/50"
        />
      </div>

      <div className="space-y-2">
        <label id="blog-form-excerpt-label" htmlFor="blog-form-excerpt" className="block text-sm font-medium">Excerpt</label>
        <textarea
          id="blog-form-excerpt"
          value={excerpt}
          onChange={(e) => setExcerpt(e.target.value)}
          placeholder="Brief description of the post"
          rows={3}
          required
          className="w-full px-3 py-2 border border-border rounded-lg bg-card focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none"
        />
      </div>

      <div className="space-y-2">
        <label id="blog-form-content-label" className="block text-sm font-medium">Content</label>
        <RichEditor content={content} onChange={setContent} onUploadImage={uploadFile} />
      </div>

      <div className="space-y-2">
        <label id="blog-form-author-label" className="block text-sm font-medium">Author</label>
        <div className="flex items-start gap-4">
          <div className="flex flex-col items-center gap-2">
            {authorAvatar ? (
              <div className="relative">
                <img src={authorAvatar} alt="Author avatar" className="w-16 h-16 rounded-full object-cover border border-border" />
                <button id="blog-form-avatar-remove" type="button" onClick={() => setAuthorAvatar("")} className="absolute -top-1 -right-1 p-0.5 rounded-full bg-destructive text-white hover:opacity-80">
                  <X size={12} />
                </button>
              </div>
            ) : (
              <button id="blog-form-avatar-upload" type="button" onClick={() => avatarInputRef.current?.click()} className="w-16 h-16 rounded-full border-2 border-dashed border-border flex items-center justify-center hover:border-muted-foreground transition-colors">
                {avatarUploading ? (
                  <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
                ) : (
                  <ImageIcon size={20} className="text-muted-foreground" />
                )}
              </button>
            )}
            <span id="blog-form-avatar-hint" className="text-xs text-muted-foreground">Photo</span>
            <input id="blog-form-avatar-input" ref={avatarInputRef} type="file" accept="image/*" className="hidden" onChange={(e) => { const file = e.target.files?.[0]; if (file) uploadAvatar(file); e.target.value = ""; }} />
          </div>
          <div className="flex-1">
            <input id="blog-form-author-name" type="text" value={authorName} onChange={(e) => setAuthorName(e.target.value)} placeholder="Author name" className="w-full px-3 py-2 border border-border rounded-lg bg-card focus:outline-none focus:ring-2 focus:ring-primary/50" />
          </div>
        </div>
      </div>

      <div className="space-y-2">
        <label id="blog-form-thumbnail-label" className="block text-sm font-medium">Thumbnail</label>
        {thumbnailUrl ? (
          <div className="relative inline-block">
            <img src={thumbnailUrl} alt="Thumbnail preview" className="max-h-40 rounded-md border border-border" />
            <button id="blog-form-thumbnail-remove" type="button" onClick={() => setThumbnailUrl("")} className="absolute -top-2 -right-2 p-1 rounded-full bg-destructive text-white hover:opacity-80">
              <X size={14} />
            </button>
          </div>
        ) : (
          <div id="blog-form-thumbnail-dropzone" onDrop={handleThumbnailDrop} onDragOver={(e) => e.preventDefault()} onClick={() => thumbnailInputRef.current?.click()} className="flex flex-col items-center justify-center gap-2 border-2 border-dashed border-border rounded-md p-8 cursor-pointer hover:border-muted-foreground transition-colors">
            {thumbnailUploading ? (
              <Loader2 size={32} className="text-muted-foreground animate-spin" />
            ) : (
              <ImageIcon size={32} className="text-muted-foreground" />
            )}
            <p id="blog-form-thumbnail-hint" className="text-sm text-muted-foreground">{thumbnailUploading ? "Uploading..." : "Drop an image here or click to upload"}</p>
          </div>
        )}
        <input id="blog-form-thumbnail-input" ref={thumbnailInputRef} type="file" accept="image/*" className="hidden" onChange={(e) => { const file = e.target.files?.[0]; if (file) uploadThumbnail(file); e.target.value = ""; }} />
      </div>

      <div className="space-y-2">
        <label id="blog-form-hero-image-label" className="block text-sm font-medium">Hero Background Image</label>
        <p id="blog-form-hero-image-desc" className="text-xs text-muted-foreground mb-2">Used as the post page header background. Falls back to a dark gradient if not provided.</p>
        {heroImageUrl ? (
          <div className="relative inline-block">
            <img src={heroImageUrl} alt="Hero image preview" className="max-h-40 rounded-md border border-border" />
            <button id="blog-form-hero-image-remove" type="button" onClick={() => setHeroImageUrl("")} className="absolute -top-2 -right-2 p-1 rounded-full bg-destructive text-white hover:opacity-80">
              <X size={14} />
            </button>
          </div>
        ) : (
          <div id="blog-form-hero-image-dropzone" onDrop={handleHeroImageDrop} onDragOver={(e) => e.preventDefault()} onClick={() => heroImageInputRef.current?.click()} className="flex flex-col items-center justify-center gap-2 border-2 border-dashed border-border rounded-md p-8 cursor-pointer hover:border-muted-foreground transition-colors">
            {heroImageUploading ? (
              <Loader2 size={32} className="text-muted-foreground animate-spin" />
            ) : (
              <ImageIcon size={32} className="text-muted-foreground" />
            )}
            <p id="blog-form-hero-image-hint" className="text-sm text-muted-foreground">{heroImageUploading ? "Uploading..." : "Drop a hero background image or click to upload"}</p>
          </div>
        )}
        <input id="blog-form-hero-image-input" ref={heroImageInputRef} type="file" accept="image/*" className="hidden" onChange={(e) => { const file = e.target.files?.[0]; if (file) uploadHeroImage(file); e.target.value = ""; }} />
      </div>

      <div className="space-y-2">
        <label id="blog-form-tags-label" htmlFor="blog-form-tags" className="block text-sm font-medium">Tags</label>
        <input id="blog-form-tags" type="text" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="ai, recruiting, interviews (comma-separated)" className="w-full px-3 py-2 border border-border rounded-lg bg-card focus:outline-none focus:ring-2 focus:ring-primary/50" />
      </div>

      <div className="space-y-2">
        <label id="blog-form-status-label" className="block text-sm font-medium">Status</label>
        <div id="blog-form-status-group" className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm">
            <input id="blog-form-status-draft" type="radio" name="status" value="draft" checked={status === "draft"} onChange={() => setStatus("draft")} />
            Draft
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input id="blog-form-status-published" type="radio" name="status" value="published" checked={status === "published"} onChange={() => setStatus("published")} />
            Published
          </label>
        </div>
      </div>

      <button id="blog-form-submit" type="submit" disabled={submitting} className="px-6 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 flex items-center gap-2">
        {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
        {submitting ? "Saving..." : submitLabel}
      </button>
    </form>
  );
}
