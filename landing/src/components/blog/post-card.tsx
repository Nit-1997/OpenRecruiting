import Link from "next/link";
import { Post } from "@/lib/blog-api";
import { ShareButton } from "@/components/blog/share-button";
import { LikeButton } from "@/components/blog/like-button";

function formatDate(dateString: string) {
  return new Date(dateString).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function PostCard({ post }: { post: Post }) {
  return (
    <Link id={`post-card-link-${post.slug}`} href={`/blogs/${post.slug}`}>
      <div
        id={`post-card-${post.slug}`}
        className="group h-full rounded-xl border border-border bg-surface hover:-translate-y-1 transition-all duration-200"
      >
        {post.thumbnailUrl ? (
          <div id={`post-card-thumb-${post.slug}`} className="h-48 rounded-t-xl overflow-hidden">
            <img
              src={post.thumbnailUrl}
              alt={post.title}
              className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
            />
          </div>
        ) : (
          <div
            id={`post-card-thumb-fallback-${post.slug}`}
            className="h-48 rounded-t-xl flex items-center justify-center"
            style={{
              background: "linear-gradient(135deg, #C5D0F5 0%, #DAE2FA 50%, #EBF0FC 100%)",
            }}
          >
            <span className="text-5xl text-white/80 font-display italic">
              {post.title.charAt(0)}
            </span>
          </div>
        )}
        <div className="p-5">
          <h2 id={`post-card-title-${post.slug}`} className="text-lg font-medium leading-tight line-clamp-2 font-display text-text-primary mb-2">
            {post.title}
          </h2>
          <p id={`post-card-excerpt-${post.slug}`} className="text-sm text-text-secondary line-clamp-3 mb-4 leading-relaxed">
            {post.excerpt}
          </p>
          <div id={`post-card-meta-${post.slug}`} className="flex items-center justify-between gap-3 text-xs text-text-muted">
            <div className="flex items-center gap-2 min-w-0">
              {post.author.avatar ? (
                <img
                  src={post.author.avatar}
                  alt={post.author.name}
                  className="w-5 h-5 rounded-full object-cover shrink-0"
                />
              ) : (
                <div className="w-5 h-5 rounded-full bg-surface-accent flex items-center justify-center text-[10px] font-medium shrink-0 text-text-muted">
                  {post.author.name.charAt(0)}
                </div>
              )}
              <span className="truncate">{post.author.name}</span>
            </div>
            <time dateTime={post.createdAt} className="shrink-0">
              {formatDate(post.createdAt)}
            </time>
          </div>
          <div id={`post-card-actions-${post.slug}`} className="flex items-center justify-end gap-3 mt-4 pt-3 border-t border-border">
            <LikeButton slug={post.slug} initialLikes={post.likes} />
            <ShareButton slug={post.slug} />
          </div>
        </div>
      </div>
    </Link>
  );
}
