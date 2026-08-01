import type { NextConfig } from "next";

const API_ORIGIN =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8004";

// The public blog read API was migrated to the v2 backend. Only the blog uses
// this base; auth/OAuth calls still go to API_ORIGIN (v1) until those migrate.
const API_V2_ORIGIN =
  process.env.NEXT_PUBLIC_API_V2_URL ?? "http://localhost:8004";

const nextConfig: NextConfig = {
  output: "standalone",
  experimental: {
    optimizePackageImports: ["lucide-react", "framer-motion"],
  },
  async rewrites() {
    return [
      // Same-origin proxy for the public blog API. Lets client-side
      // fetches (search, sort, load-more, like) skip CORS entirely.
      {
        source: "/api/blog/:path*",
        destination: `${API_V2_ORIGIN}/api/v2/public/blog/:path*`,
      },
    ];
  },
  async redirects() {
    return [
      // Catch the legacy proxy-era pattern; canonical is /blogs/<slug>.
      {
        source: "/blog/:slug",
        destination: "/blogs/:slug",
        permanent: true,
      },
    ];
  },
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "i.ytimg.com",
      },
      {
        protocol: "https",
        hostname: "images.unsplash.com",
      },
      {
        protocol: "https",
        hostname: "example-blog-images.s3.amazonaws.com",
      },
    ],
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(self), geolocation=()",
          },
        ],
      },
      {
        source: "/:path*.(svg|ico|png|jpg|jpeg|webp)",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=31536000, immutable",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
