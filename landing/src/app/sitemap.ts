import type { MetadataRoute } from "next";
import { serverBackendUrl } from "@/lib/backend-url";

// Sitemap generation runs in the container, so this is the compose address, not
// the browser's NEXT_PUBLIC_API_V2_URL.
const BLOG_API_URL = serverBackendUrl();

async function fetchBlogSlugs(): Promise<{ slug: string; updatedAt: string }[]> {
  try {
    const res = await fetch(`${BLOG_API_URL}/api/v2/public/blog/posts?page_size=1000`, {
      next: { revalidate: 86400 },
    });
    if (!res.ok) return [];
    const data = await res.json();
    return (data.posts ?? []).map((p: { slug: string; updated_at: string }) => ({
      slug: p.slug,
      updatedAt: p.updated_at,
    }));
  } catch {
    return [];
  }
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const posts = await fetchBlogSlugs();

  const blogEntries: MetadataRoute.Sitemap = posts.map((p) => ({
    url: `http://localhost:3000/blogs/${p.slug}`,
    lastModified: new Date(p.updatedAt),
    changeFrequency: "monthly",
    priority: 0.7,
  }));

  return [
    { url: "http://localhost:3000", lastModified: new Date(), changeFrequency: "weekly", priority: 1.0 },
    { url: "http://localhost:3000/onboarding", lastModified: new Date(), changeFrequency: "monthly", priority: 0.8 },
    { url: "http://localhost:3000/blogs", lastModified: new Date(), changeFrequency: "daily", priority: 0.8 },
    { url: "http://localhost:3000/login", lastModified: new Date(), changeFrequency: "monthly", priority: 0.5 },
    { url: "http://localhost:3000/terms", lastModified: new Date(), changeFrequency: "monthly", priority: 0.3 },
    { url: "http://localhost:3000/privacy", lastModified: new Date(), changeFrequency: "monthly", priority: 0.3 },
    ...blogEntries,
  ];
}
