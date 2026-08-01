import sanitizeHtml from "sanitize-html";

// Hostnames whose iframes are safe to embed in blog posts (video embeds only).
const ALLOWED_IFRAME_HOSTNAMES = [
  "www.youtube.com",
  "youtube.com",
  "www.youtube-nocookie.com",
  "youtube-nocookie.com",
  "youtu.be",
  "player.vimeo.com",
];

// Pure JS (no jsdom): safe to run inside a Vercel serverless function on any
// Node version. Strips <script>, event handlers and javascript: URLs; keeps the
// formatting/embed surface the CMS uses. Iframes survive only from the hosts above.
const SANITIZE_OPTIONS: sanitizeHtml.IOptions = {
  allowedTags: [...sanitizeHtml.defaults.allowedTags, "img", "iframe"],
  allowedAttributes: {
    "*": ["class", "id", "style"],
    a: ["href", "name", "target", "rel", "title"],
    img: ["src", "srcset", "alt", "title", "width", "height", "loading"],
    iframe: [
      "src",
      "width",
      "height",
      "title",
      "allow",
      "allowfullscreen",
      "frameborder",
      "loading",
      "referrerpolicy",
    ],
  },
  allowedSchemes: ["http", "https", "mailto", "tel"],
  allowedSchemesByTag: { img: ["http", "https", "data"] },
  allowedIframeHostnames: ALLOWED_IFRAME_HOSTNAMES,
  allowIframeRelativeUrls: false,
};

// CMS content is trusted-ish (only OpenRecruiting staff publish), but defense-in-depth:
// strip anything that could execute on localhost:3000 before injecting it.
export function sanitizeBlogHtml(content: string): string {
  return sanitizeHtml(content, SANITIZE_OPTIONS);
}

export function ContentRenderer({ content }: { content: string }) {
  const safe = sanitizeBlogHtml(content);
  return (
    <div
      className="prose text-text-secondary"
      dangerouslySetInnerHTML={{ __html: safe }}
    />
  );
}
