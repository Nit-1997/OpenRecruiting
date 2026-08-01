import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "OpenRecruiting - Interview Intelligence Platform";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OgImage() {
  return new ImageResponse(
    (
      <div
        id="og-image-container"
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: "#6b5c4d",
          color: "#f5f0eb",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        <div
          id="og-logo-section"
          style={{
            display: "flex",
            alignItems: "center",
            gap: "16px",
            marginBottom: "32px",
          }}
        >
          <svg
            width="64"
            height="64"
            viewBox="0 0 120 120"
            xmlns="http://www.w3.org/2000/svg"
          >
            <defs>
              <path
                id="blade"
                d="M 0 -12.5 L 0 -45 A 12.5 12.5 0 0 1 25 -45 L 25 -12.5 A 12.5 12.5 0 0 1 0 -12.5 Z"
              />
            </defs>
            <g transform="translate(60, 60)">
              <use
                href="#blade"
                transform="rotate(-150) translate(0, 10)"
                fill="#f5f0eb"
              />
              <use
                href="#blade"
                transform="rotate(-30) translate(0, 10)"
                fill="#f5f0eb"
              />
              <use
                href="#blade"
                transform="rotate(90) translate(0, 10)"
                fill="#f5f0eb"
              />
              <circle cx="0" cy="0" r="11" fill="#f5f0eb" />
            </g>
          </svg>
          <span style={{ fontSize: "64px", fontWeight: 700 }}>localhost:3000</span>
        </div>
        <div
          id="og-tagline"
          style={{
            fontSize: "32px",
            fontWeight: 400,
            opacity: 0.9,
            textAlign: "center",
            maxWidth: "800px",
          }}
        >
          AI-Powered Interview Intelligence Platform
        </div>
        <div
          id="og-subtitle"
          style={{
            fontSize: "20px",
            fontWeight: 300,
            opacity: 0.7,
            marginTop: "16px",
            textAlign: "center",
          }}
        >
          Structured interviews. Real-time guidance. Instant feedback.
        </div>
      </div>
    ),
    { ...size }
  );
}
