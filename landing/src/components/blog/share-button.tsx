"use client";

import { useState } from "react";
import { Link2, Check } from "lucide-react";

export function ShareButton({ slug, className }: { slug: string; className?: string }) {
  const [copied, setCopied] = useState(false);

  function handleCopy(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    const url = `${window.location.origin}/blogs/${slug}`;
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      title="Copy link"
      className={`inline-flex items-center gap-1 text-text-muted hover:text-text-primary transition-colors ${className ?? ""}`}
    >
      {copied ? <Check size={14} /> : <Link2 size={14} />}
      {copied && <span className="text-xs">Copied!</span>}
    </button>
  );
}
