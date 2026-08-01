"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { PostCard } from "@/components/blog/post-card";
import { fetchPosts, Post } from "@/lib/blog-api";
import { Search, Loader2 } from "lucide-react";

type SortOption = "latest" | "oldest" | "top";

export function PostListing({
  initialPosts,
  totalPosts,
}: {
  initialPosts: Post[];
  totalPosts: number;
}) {
  const [posts, setPosts] = useState<Post[]>(initialPosts);
  const [total, setTotal] = useState(totalPosts);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortOption>("latest");
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const searchAndSort = useCallback(async (searchQuery: string, sortOption: SortOption) => {
    setLoading(true);
    try {
      const result = await fetchPosts(1, 12, searchQuery, sortOption);
      setPosts(result.posts);
      setTotal(result.total);
      setPage(1);
    } finally {
      setLoading(false);
    }
  }, []);

  function handleSearchChange(value: string) {
    setQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      searchAndSort(value, sort);
    }, 400);
  }

  function handleSortChange(option: SortOption) {
    // Cancel any pending search-debounce so it can't overwrite this sort fetch
    // with stale results captured before the sort changed.
    if (debounceRef.current) clearTimeout(debounceRef.current);
    setSort(option);
    searchAndSort(query, option);
  }

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  async function loadMore() {
    setLoadingMore(true);
    try {
      const nextPage = page + 1;
      const result = await fetchPosts(nextPage, 12, query, sort);
      setPosts((prev) => [...prev, ...result.posts]);
      setTotal(result.total);
      setPage(nextPage);
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div id="post-listing">
      <div id="post-listing-controls" className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 mb-8">
        <div className="relative flex-1">
          <Search size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            id="post-listing-search"
            type="text"
            value={query}
            onChange={(e) => handleSearchChange(e.target.value)}
            placeholder="Search posts..."
            className="w-full pl-10 pr-4 py-2.5 text-sm rounded-full border border-border bg-surface focus:outline-none focus:ring-2 focus:ring-[#C5D0F5] transition-all"
          />
        </div>
        <div id="post-listing-sort" className="flex items-center gap-1 rounded-full border border-border bg-surface p-0.5">
          {(["latest", "top", "oldest"] as SortOption[]).map((option) => (
            <button
              key={option}
              id={`post-listing-sort-${option}`}
              onClick={() => handleSortChange(option)}
              className={`px-4 py-1.5 text-xs font-medium rounded-full capitalize transition-colors ${
                sort === option
                  ? "bg-cta-bg text-cta-text"
                  : "text-text-muted hover:text-text-primary"
              }`}
            >
              {option}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div id="post-listing-loading" className="flex items-center justify-center py-20">
          <Loader2 className="w-6 h-6 animate-spin text-text-muted" />
        </div>
      ) : posts.length === 0 ? (
        <p id="post-listing-empty" className="text-center text-text-muted py-20 font-display italic text-xl">
          {query ? "No posts match your search." : "No posts yet. Check back soon!"}
        </p>
      ) : (
        <>
          <div id="post-listing-grid" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {posts.map((post) => (
              <PostCard key={post.id} post={post} />
            ))}
          </div>
          {posts.length < total && (
            <div id="post-listing-load-more" className="flex justify-center mt-12">
              <button
                id="post-listing-load-more-btn"
                onClick={loadMore}
                disabled={loadingMore}
                className="h-12 px-8 rounded-full border border-[#111111] text-sm font-medium text-[#111111] bg-transparent hover:bg-[#111111] hover:text-white transition-colors disabled:opacity-50 flex items-center gap-2"
              >
                {loadingMore && <Loader2 className="w-4 h-4 animate-spin" />}
                {loadingMore ? "Loading..." : "Load More"}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
