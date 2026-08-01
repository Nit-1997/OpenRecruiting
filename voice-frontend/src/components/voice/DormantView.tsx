"use client";

export default function DormantView() {
  return (
    <div
      id="dormant-view-container"
      className="fixed inset-0 flex flex-col items-center justify-center"
      style={{ backgroundColor: "#0a0a0a" }}
    >
      <div id="dormant-logo-mark" className="mb-8">
        <svg
          width="72"
          height="72"
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
            <use href="#blade" transform="rotate(-150) translate(0, 10)" fill="#ffffff" />
            <use href="#blade" transform="rotate(-30) translate(0, 10)" fill="#ffffff" />
            <use href="#blade" transform="rotate(90) translate(0, 10)" fill="#ffffff" />
            <circle cx="0" cy="0" r="11" fill="#ffffff" />
          </g>
        </svg>
      </div>

      <div id="dormant-wordmark" className="mb-10" style={{ fontFamily: "var(--font-pacifico), cursive" }}>
        <span style={{ color: "#e5e5e5", fontSize: "28px" }}>scout</span>
        <span style={{ color: "#a3a3a3", fontSize: "28px" }}>.ai</span>
      </div>

      <div id="dormant-status" className="flex items-center gap-2.5">
        <span
          id="dormant-pulse-dot"
          className="inline-block w-2 h-2 rounded-full animate-pulse"
          style={{ backgroundColor: "#ef4444" }}
        />
        <span style={{ color: "#737373", fontSize: "13px", letterSpacing: "0.05em" }}>
          Recording in progress
        </span>
      </div>
    </div>
  );
}
