import Link from "next/link";
import Image from "next/image";
import { fetchPosts } from "@/lib/blog-api";

interface RelatedPostsProps {
  currentSlug: string;
  tags: string[];
}

export async function RelatedPosts({ currentSlug, tags }: RelatedPostsProps) {
  const { posts } = await fetchPosts(1, 100);

  const candidates = posts.filter((p) => p.slug !== currentSlug && p.status === "published");

  const scored = candidates
    .map((post) => ({
      post,
      score: post.tags.filter((t) => tags.includes(t)).length,
    }))
    .sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      return new Date(b.post.createdAt).getTime() - new Date(a.post.createdAt).getTime();
    })
    .slice(0, 3);

  if (scored.length === 0) return null;

  return (
    <section id="related-posts" className="max-w-[680px] mx-auto px-6 py-14 border-t border-border">
      <h2 id="related-posts-heading" className="text-2xl font-display font-light mb-6 text-text-primary">
        Related reading
      </h2>
      <div id="related-posts-list" className="space-y-5">
        {scored.map(({ post }) => (
          <Link
            key={post.slug}
            id={`related-post-link-${post.slug}`}
            href={`/blogs/${post.slug}`}
            className="block group rounded-lg hover:bg-surface transition-colors p-3 -mx-3"
          >
            <div className="flex gap-4 items-start">
              {post.thumbnailUrl ? (
                <Image
                  id={`related-post-thumb-${post.slug}`}
                  src={post.thumbnailUrl}
                  alt=""
                  width={120}
                  height={80}
                  className="rounded-md object-cover flex-shrink-0 w-[120px] h-[80px]"
                />
              ) : (
                <div
                  id={`related-post-thumb-fallback-${post.slug}`}
                  className="w-[120px] h-[80px] rounded-md flex-shrink-0 flex items-center justify-center"
                  style={{
                    background: "linear-gradient(135deg, #C5D0F5 0%, #DAE2FA 50%, #EBF0FC 100%)",
                  }}
                >
                  <span className="text-2xl text-white/80 font-display italic">
                    {post.title.charAt(0)}
                  </span>
                </div>
              )}
              <div className="min-w-0 flex-1">
                <h3 id={`related-post-title-${post.slug}`} className="font-medium text-text-primary group-hover:underline line-clamp-2">
                  {post.title}
                </h3>
                <p id={`related-post-excerpt-${post.slug}`} className="text-sm text-text-secondary mt-1 line-clamp-2">
                  {post.excerpt}
                </p>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
