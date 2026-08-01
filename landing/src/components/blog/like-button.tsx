"use client";

import { useState } from "react";
import { Heart } from "lucide-react";
import { likePost } from "@/lib/blog-api";

export function LikeButton({
  slug,
  initialLikes,
  size = "default",
}: {
  slug: string;
  initialLikes: number;
  size?: "default" | "lg";
}) {
  const [likes, setLikes] = useState(initialLikes || 0);
  const [liked, setLiked] = useState(false);
  const [animating, setAnimating] = useState(false);

  async function handleLike(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    if (liked) return;

    setLiked(true);
    setLikes((prev) => prev + 1);
    setAnimating(true);
    setTimeout(() => setAnimating(false), 300);

    try {
      const { likes: serverLikes } = await likePost(slug);
      setLikes(serverLikes);
    } catch {
      // Keep optimistic state
    }
  }

  const iconSize = size === "lg" ? 20 : 14;

  return (
    <button
      id={`like-btn-${slug}`}
      type="button"
      onClick={handleLike}
      title={liked ? "Liked" : "Like this post"}
      className={`inline-flex items-center gap-1.5 transition-all duration-200 ${
        liked ? "text-red-500" : "text-text-muted hover:text-red-500"
      } ${animating ? "scale-125" : "scale-100"}`}
    >
      <Heart
        size={iconSize}
        className={`transition-all duration-200 ${liked ? "fill-red-500 stroke-red-500" : ""}`}
      />
      <span className={`${size === "lg" ? "text-sm" : "text-xs"} tabular-nums`}>
        {likes}
      </span>
    </button>
  );
}
