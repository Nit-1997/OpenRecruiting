import type { Metadata } from "next";
import { notFound } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { ArrowLeft } from "lucide-react";
import { fetchPostBySlug } from "@/lib/blog-api";
import { Header } from "@/components/ui/header";
import { Footer } from "@/components/ui/footer";
import { ContentRenderer } from "@/components/blog/content-renderer";
import { ShareButton } from "@/components/blog/share-button";
import { LikeButton } from "@/components/blog/like-button";
import { RelatedPosts } from "@/components/blog/related-posts";

export const dynamic = "force-dynamic";

const SITE_URL = "http://localhost:3000";
const PUBLISHER_LOGO = "http://localhost:3000/zymo-logo.svg";

function formatDate(dateString: string) {
  return new Date(dateString).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const post = await fetchPostBySlug(slug);
  if (!post) return { title: "Post not found" };

  const url = `${SITE_URL}/blogs/${post.slug}`;
  const ogImage = post.heroImageUrl || post.thumbnailUrl;

  return {
    title: post.title,
    description: post.excerpt,
    authors: [{ name: post.author.name }],
    alternates: { canonical: url },
    openGraph: {
      type: "article",
      url,
      title: post.title,
      description: post.excerpt,
      siteName: "OpenRecruiting Blog",
      images: ogImage ? [{ url: ogImage }] : [],
      publishedTime: post.createdAt,
      modifiedTime: post.updatedAt,
      authors: [post.author.name],
    },
    twitter: {
      card: "summary_large_image",
      title: post.title,
      description: post.excerpt,
      images: ogImage ? [ogImage] : [],
    },
  };
}

export default async function BlogPostPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const post = await fetchPostBySlug(slug);

  if (!post) {
    notFound();
  }

  const url = `${SITE_URL}/blogs/${post.slug}`;
  const ogImage = post.heroImageUrl || post.thumbnailUrl;

  const articleSchema = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: post.title,
    description: post.excerpt,
    ...(ogImage && { image: ogImage }),
    datePublished: post.createdAt,
    dateModified: post.updatedAt,
    author: {
      "@type": "Person",
      name: post.author.name,
      url: "http://localhost:3000",
    },
    publisher: {
      "@type": "Organization",
      name: "OpenRecruiting",
      url: "http://localhost:3000",
      logo: {
        "@type": "ImageObject",
        url: PUBLISHER_LOGO,
      },
    },
    mainEntityOfPage: {
      "@type": "WebPage",
      "@id": url,
    },
    keywords: post.tags.join(", "),
  };

  return (
    <div id="blog-post-page" className="blog-page min-h-screen flex flex-col">
      <script
        id="blog-post-jsonld"
        type="application/ld+json"
        // Escape `<` so a post field containing `</script>` cannot break out of this tag.
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(articleSchema).replace(/</g, "\\u003c"),
        }}
      />
      <Header />

      <main id="blog-post-main" className="min-h-screen">
        <section
          id="blog-post-hero"
          className="relative overflow-hidden"
          style={post.heroImageUrl
            ? { background: "#0A0A0A" }
            : { background: "linear-gradient(180deg, #0A0A0A 0%, #1a1a2e 50%, #16213e 100%)" }
          }
        >
          {post.heroImageUrl ? (
            <>
              <Image
                id="blog-post-hero-bg"
                src={post.heroImageUrl}
                alt=""
                fill
                priority
                sizes="100vw"
                className="object-cover"
              />
              <div id="blog-post-hero-overlay" className="absolute inset-0 bg-black/60" />
            </>
          ) : (
            <div
              id="blog-post-hero-glow"
              className="absolute inset-0"
              style={{
                background: "radial-gradient(ellipse at 50% 100%, rgba(197,208,245,0.12) 0%, transparent 50%)",
              }}
            />
          )}
          <div className="relative z-10 max-w-[680px] mx-auto px-6 pt-28 pb-16">
            <Link
              id="blog-post-back"
              href="/blogs"
              className="inline-flex items-center gap-1.5 text-sm text-white/50 hover:text-white/80 transition-colors mb-8"
            >
              <ArrowLeft className="w-4 h-4" />
              Back to all posts
            </Link>

            <h1 id="blog-post-title" className="text-4xl sm:text-5xl md:text-[56px] font-light tracking-tight mb-6 font-display text-white leading-[1.1]">
              {post.title}
            </h1>
            <div id="blog-post-meta" className="flex items-center justify-between">
              <div className="flex items-center gap-3 text-sm">
                {post.author.avatar ? (
                  <Image
                    id="blog-post-avatar"
                    src={post.author.avatar}
                    alt={post.author.name}
                    width={36}
                    height={36}
                    className="w-9 h-9 rounded-full object-cover border-2 border-white/20"
                  />
                ) : (
                  <div id="blog-post-avatar-fallback" className="w-9 h-9 rounded-full bg-white/10 flex items-center justify-center text-xs font-medium text-white/70 border-2 border-white/20">
                    {post.author.name.charAt(0)}
                  </div>
                )}
                <div>
                  <span id="blog-post-author" className="text-white/90 block">{post.author.name}</span>
                  <time id="blog-post-date" dateTime={post.createdAt} className="text-white/40 text-xs">
                    {formatDate(post.createdAt)}
                  </time>
                </div>
              </div>
              <div id="blog-post-header-actions" className="flex items-center gap-3 text-white/60">
                <LikeButton slug={post.slug} initialLikes={post.likes} size="lg" />
                <ShareButton slug={post.slug} className="text-sm" />
              </div>
            </div>
          </div>
        </section>

        <article id="blog-post-article" className="max-w-[680px] mx-auto px-6 py-14 bg-background">
          <ContentRenderer content={post.content} />

          <div id="blog-post-footer-actions" className="flex items-center gap-4 mt-12 pt-6 border-t border-border">
            <LikeButton slug={post.slug} initialLikes={post.likes} size="lg" />
            <ShareButton slug={post.slug} className="text-sm" />
          </div>
        </article>

        <RelatedPosts currentSlug={post.slug} tags={post.tags} />
      </main>

      <Footer />
    </div>
  );
}
