import { fetchPosts } from "@/lib/blog-api";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const BASE_URL = "http://localhost:3000";

export async function GET() {
  const { posts } = await fetchPosts(1, 1000);
  const published = posts.filter((p) => p.status === "published");

  const lines = [
    "# OpenRecruiting Blog",
    "",
    "> Insights on AI-powered recruiting, interview intelligence, and the future of hiring from the team at OpenRecruiting.",
    "",
    "OpenRecruiting builds interview intelligence software that captures structured signal from every interview a hiring team runs, turning unstructured conversations into evidence-based hiring decisions.",
    "",
    "## Blog Posts",
    "",
    ...published.map((p) => `- [${p.title}](${BASE_URL}/blogs/${p.slug}): ${p.excerpt}`),
    "",
    "## About OpenRecruiting",
    "",
    `- [OpenRecruiting homepage](${BASE_URL})`,
    `- [Blog index](${BASE_URL}/blogs)`,
    "",
  ];

  return new Response(lines.join("\n"), {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=300, s-maxage=300",
    },
  });
}
