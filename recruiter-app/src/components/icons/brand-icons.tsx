import type { SVGProps } from 'react';

/**
 * Brand icons for the integrations panel. Third-party marks render from
 * raw brand PNG/WEBP assets under /public/brand/ so we use the canonical
 * logos rather than hand-rolled SVGs. Keeps signatures uniform — every
 * component accepts { className, id } — so they can be swapped behind
 * the same type without caller refactors.
 */

interface BrandImgProps {
  className?: string | undefined;
  id?: string | undefined;
}

/**
 * OpenRecruiting icon — inline SVG using currentColor so the mark flips cleanly
 * between light and dark mode via the parent's text color. Prefer this
 * over /public/brand-icon.svg (hardcoded black fills), which renders as
 * a dark-on-dark blob in dark mode.
 */
export function BrandIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 120 120"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="OpenRecruiting"
      fill="currentColor"
      {...props}
    >
      <title>OpenRecruiting</title>
      <defs>
        <path
          id="brand-blade"
          d="M 0 -12.5 L 0 -45 A 12.5 12.5 0 0 1 25 -45 L 25 -12.5 A 12.5 12.5 0 0 1 0 -12.5 Z"
        />
      </defs>
      <g transform="translate(60, 60)">
        <use href="#brand-blade" transform="rotate(-150) translate(0, 10)" />
        <use href="#brand-blade" transform="rotate(-30) translate(0, 10)" />
        <use href="#brand-blade" transform="rotate(90) translate(0, 10)" />
        <circle cx="0" cy="0" r="11" />
      </g>
    </svg>
  );
}

export function SlackIcon({ className, id }: BrandImgProps) {
  return (
    <svg
      id={id}
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <title>Slack</title>
      <path
        d="M5.042 15.165a2.083 2.083 0 0 1-2.083 2.083A2.083 2.083 0 0 1 .876 15.165c0-1.15.934-2.083 2.083-2.083h2.083v2.083Zm1.042 0c0-1.15.933-2.083 2.083-2.083 1.15 0 2.083.933 2.083 2.083v5.208a2.083 2.083 0 0 1-2.083 2.083 2.083 2.083 0 0 1-2.083-2.083v-5.208Z"
        fill="#E01E5A"
      />
      <path
        d="M8.167 6.792a2.083 2.083 0 0 1-2.083-2.083c0-1.15.933-2.084 2.083-2.084 1.15 0 2.083.934 2.083 2.084v2.083H8.167Zm0 1.058c1.15 0 2.083.933 2.083 2.083a2.083 2.083 0 0 1-2.083 2.083H2.959A2.083 2.083 0 0 1 .876 9.933c0-1.15.933-2.083 2.083-2.083h5.208Z"
        fill="#36C5F0"
      />
      <path
        d="M16.542 9.933c0-1.15.933-2.083 2.083-2.083 1.15 0 2.083.933 2.083 2.083a2.083 2.083 0 0 1-2.083 2.083h-2.083V9.933Zm-1.042 0a2.083 2.083 0 0 1-2.083 2.083 2.083 2.083 0 0 1-2.083-2.083V4.709c0-1.15.933-2.084 2.083-2.084 1.15 0 2.083.934 2.083 2.084v5.224Z"
        fill="#2EB67D"
      />
      <path
        d="M13.375 18.292c1.15 0 2.083.933 2.083 2.083a2.083 2.083 0 0 1-2.083 2.083 2.083 2.083 0 0 1-2.083-2.083v-2.083h2.083Zm0-1.042a2.083 2.083 0 0 1-2.083-2.083c0-1.15.933-2.084 2.083-2.084h5.225c1.15 0 2.083.934 2.083 2.084a2.083 2.083 0 0 1-2.083 2.083h-5.225Z"
        fill="#ECB22E"
      />
    </svg>
  );
}

/**
 * Ashby mark — rendered from the official Ashby brand WEBP saved under
 * /public/brand/ashby.webp. Kept as a component with the same
 * (className / id) call-site signature as the other brand icons so
 * callers can swap inline SVG for image without touching layout.
 */
export function AshbyIcon({ className, id }: BrandImgProps) {
  return (
    // biome-ignore lint/performance/noImgElement: static brand mark; Next/Image optimization is unnecessary overhead
    <img id={id} src="/brand/ashby.webp" alt="Ashby" className={className} draggable={false} />
  );
}

/**
 * Greenhouse mark — rendered from the official Greenhouse brand WEBP
 * saved under /public/brand/greenhouse.webp.
 */
export function GreenhouseIcon({ className, id }: BrandImgProps) {
  return (
    // biome-ignore lint/performance/noImgElement: static brand mark; Next/Image optimization is unnecessary overhead
    <img
      id={id}
      src="/brand/greenhouse.webp"
      alt="Greenhouse"
      className={className}
      draggable={false}
    />
  );
}

/**
 * Lever mark — rendered from the official Lever brand WEBP saved under
 * /public/brand/lever.webp.
 */
export function LeverIcon({ className, id }: BrandImgProps) {
  return (
    // biome-ignore lint/performance/noImgElement: static brand mark; Next/Image optimization is unnecessary overhead
    <img id={id} src="/brand/lever.webp" alt="Lever" className={className} draggable={false} />
  );
}

export function AgentIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
      <title>OpenRecruiting agent</title>
      <rect x="2" y="2" width="20" height="20" rx="5" fill="#111111" />
      <path d="M12 6.5 14 11l4.5 1-4.5 1-2 4.5-2-4.5-4.5-1 4.5-1 2-4.5Z" fill="#F97316" />
    </svg>
  );
}

/**
 * Claude (Anthropic) mark — rendered from the official Claude color SVG
 * saved under /public/brand/claude.svg.
 */
export function ClaudeIcon({ className, id }: BrandImgProps) {
  return (
    // biome-ignore lint/performance/noImgElement: static brand mark; Next/Image optimization is unnecessary overhead
    <img id={id} src="/brand/claude.svg" alt="Claude" className={className} draggable={false} />
  );
}
