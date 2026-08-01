import { describe, it, expect } from "vitest";
import { sanitizeBlogHtml } from "./content-renderer";

describe("sanitizeBlogHtml", () => {
  it("strips <script> tags and their contents", () => {
    const out = sanitizeBlogHtml('<p>hi</p><script>alert(1)</script>');
    expect(out).toContain("<p>hi</p>");
    expect(out).not.toContain("<script");
    expect(out).not.toContain("alert(1)");
  });

  it("strips inline event handlers", () => {
    const out = sanitizeBlogHtml('<img src="https://x/y.png" onerror="alert(1)">');
    expect(out).not.toContain("onerror");
  });

  it("strips javascript: URLs on links", () => {
    const out = sanitizeBlogHtml('<a href="javascript:alert(1)">x</a>');
    expect(out).not.toContain("javascript:");
  });

  it("keeps iframes from YouTube", () => {
    const out = sanitizeBlogHtml(
      '<iframe src="https://www.youtube.com/embed/abc123" allowfullscreen></iframe>'
    );
    expect(out).toContain("youtube.com/embed/abc123");
    expect(out).toContain("<iframe");
  });

  it("keeps iframes from Vimeo", () => {
    const out = sanitizeBlogHtml('<iframe src="https://player.vimeo.com/video/123"></iframe>');
    expect(out).toContain("player.vimeo.com/video/123");
  });

  it("removes iframes from non-allowed hosts", () => {
    const out = sanitizeBlogHtml('<iframe src="https://evil.example.com/x"></iframe>');
    expect(out).not.toContain("evil.example.com");
  });

  it("preserves normal blog formatting", () => {
    const html =
      '<h2>Title</h2><p>A <strong>bold</strong> <a href="http://localhost:3000">link</a>.</p>' +
      '<img src="https://example-blog-images.s3.amazonaws.com/blog/x.png" alt="x">';
    const out = sanitizeBlogHtml(html);
    expect(out).toContain("<h2>Title</h2>");
    expect(out).toContain("<strong>bold</strong>");
    expect(out).toContain('href="http://localhost:3000"');
    expect(out).toContain('src="https://example-blog-images.s3.amazonaws.com/blog/x.png"');
  });
});
