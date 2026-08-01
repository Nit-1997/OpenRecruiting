import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/", "/onboarding", "/login", "/blogs"],
        disallow: [
          "/dashboard/",
          "/feedback/",
          "/verify",
          "/set-password",
          "/signup",
          "/auth/",
          "/api/",
        ],
      },
    ],
    sitemap: "http://localhost:3000/sitemap.xml",
  };
}
