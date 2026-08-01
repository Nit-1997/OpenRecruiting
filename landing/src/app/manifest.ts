import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "OpenRecruiting - Interview Intelligence Platform",
    short_name: "OpenRecruiting",
    description:
      "AI-powered interview intelligence platform. Run structured interviews, get real-time guidance, and generate instant feedback.",
    start_url: "/",
    display: "standalone",
    background_color: "#f5f0eb",
    theme_color: "#6b5c4d",
    icons: [
      {
        src: "/icon.svg",
        sizes: "any",
        type: "image/svg+xml",
      },
    ],
  };
}
