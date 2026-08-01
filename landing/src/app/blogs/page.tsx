import type { Metadata } from "next";
import { fetchPosts } from "@/lib/blog-api";
import { Header } from "@/components/ui/header";
import { Footer } from "@/components/ui/footer";
import { PostListing } from "@/components/blog/post-listing";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "The Signal Standard | OpenRecruiting Blog",
  description:
    "Insights on AI-powered recruiting, interview intelligence, and the future of hiring from the team at OpenRecruiting.",
  alternates: { canonical: "http://localhost:3000/blogs" },
  openGraph: {
    type: "website",
    url: "http://localhost:3000/blogs",
    title: "The Signal Standard | OpenRecruiting Blog",
    description:
      "Insights on AI-powered recruiting, interview intelligence, and the future of hiring.",
    siteName: "OpenRecruiting Blog",
  },
  twitter: {
    card: "summary_large_image",
    title: "The Signal Standard | OpenRecruiting Blog",
    description:
      "Insights on AI-powered recruiting, interview intelligence, and the future of hiring.",
  },
};

export default async function BlogListingPage() {
  const { posts, total } = await fetchPosts(1, 12);

  return (
    <div id="blog-listing-page" className="blog-page min-h-screen flex flex-col">
      <Header />

      <main id="blog-listing-main" className="min-h-screen">
        <section
          id="blog-hero"
          className="relative overflow-hidden"
          style={{ background: "linear-gradient(180deg, #0A0A0A 0%, #1a1a2e 50%, #16213e 100%)" }}
        >
          <div
            id="blog-hero-gradient-overlay"
            className="absolute inset-0"
            style={{
              background: "radial-gradient(ellipse at 50% 80%, rgba(197,208,245,0.15) 0%, transparent 60%)",
            }}
          />
          <div className="relative z-10 max-w-[960px] mx-auto px-6 pt-28 pb-20 text-center">
            <p id="blog-hero-label" className="font-mono-label text-white/40 mb-5 animate-hero-fade-up-1">
              OpenRecruiting Blog
            </p>
            <h1 id="blog-hero-title" className="text-5xl sm:text-6xl md:text-7xl font-light tracking-tight mb-5 font-display text-white leading-[1.1] animate-hero-fade-up-2">
              The Signal{" "}
              <span className="italic">Standard</span>
            </h1>
            <p id="blog-hero-subtitle" className="text-lg md:text-xl text-white/70 max-w-xl mx-auto leading-relaxed animate-hero-fade-up-3">
              Defining the principles behind evidence-based hiring.
            </p>
          </div>
        </section>

        <section id="blog-post-grid" className="max-w-[960px] mx-auto px-6 py-14 bg-background">
          <PostListing initialPosts={posts} totalPosts={total} />
        </section>
      </main>

      <Footer />
    </div>
  );
}
