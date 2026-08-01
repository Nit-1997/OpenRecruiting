// Server-side fetches hit the backend directly; client-side fetches go
// through the same-origin /api/blog rewrite (see next.config.ts) to avoid CORS.
const API_BASE =
  typeof window === "undefined"
    ? `${process.env.NEXT_PUBLIC_API_V2_URL ?? "http://localhost:8004"}/api/v2/public/blog`
    : "/api/blog";

export interface Author {
  name: string;
  avatar?: string;
}

export interface Post {
  id: string;
  slug: string;
  title: string;
  excerpt: string;
  content: string;
  thumbnailUrl?: string;
  heroImageUrl?: string;
  author: Author;
  tags: string[];
  likes: number;
  status: string;
  createdAt: string;
  updatedAt: string;
}

export interface PostListResponse {
  posts: Post[];
  total: number;
  page: number;
  pageSize: number;
}

function transformPost(raw: Record<string, unknown>): Post {
  return {
    id: raw.id as string,
    slug: raw.slug as string,
    title: raw.title as string,
    excerpt: raw.excerpt as string,
    content: raw.content as string,
    thumbnailUrl: (raw.thumbnail_url as string) || undefined,
    heroImageUrl: (raw.hero_image_url as string) || undefined,
    author: {
      name: raw.author_name as string,
      avatar: (raw.author_avatar as string) || undefined,
    },
    tags: (raw.tags as string[]) || [],
    likes: (raw.likes as number) || 0,
    status: raw.status as string,
    createdAt: raw.created_at as string,
    updatedAt: raw.updated_at as string,
  };
}

export async function fetchPosts(
  page = 1,
  pageSize = 12,
  search = "",
  sort = "latest"
): Promise<PostListResponse> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    sort,
  });
  if (search) params.set("search", search);

  const res = await fetch(`${API_BASE}/posts?${params}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    return { posts: [], total: 0, page, pageSize };
  }
  const data = await res.json();
  return {
    posts: (data.posts || []).map(transformPost),
    total: data.total || 0,
    page: data.page || page,
    pageSize: data.page_size || pageSize,
  };
}

export async function fetchPostBySlug(slug: string): Promise<Post | null> {
  const res = await fetch(`${API_BASE}/posts/${slug}`, {
    cache: "no-store",
  });
  if (!res.ok) return null;
  const data = await res.json();
  return transformPost(data);
}

export async function likePost(slug: string): Promise<{ likes: number }> {
  const res = await fetch(`${API_BASE}/posts/${slug}/like`, {
    method: "POST",
  });
  if (!res.ok) throw new Error("Failed to like");
  return res.json();
}
