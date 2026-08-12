"use client";

import Link from "next/link";
import Image from "next/image";
import { useAnalytics } from "@/hooks/useAnalytics";

function Footer() {
  const { trackEvent } = useAnalytics();


  return (
    <footer id="main-footer" className="bg-[var(--lp-bg)] border-t border-[var(--lp-border)]">
      <div id="footer-inner" className="max-w-[960px] mx-auto px-6 py-16">
        <div id="footer-grid" className="grid grid-cols-1 md:grid-cols-3 gap-10 md:gap-8">
          <div id="footer-brand" className="md:col-span-1">
            <Link href="/" id="footer-logo-link" className="flex items-center gap-2 mb-4">
              <Image
                id="footer-logo-icon"
                src="/zymo-logo.svg"
                alt="OpenRecruiting Logo"
                width={32}
                height={32}
              />
              <span id="footer-logo-text" className="text-lg tracking-tight font-[family-name:var(--font-pacifico)]">
                <span className="text-[var(--lp-text-primary)]">openrecruiting</span>
                <span className="text-[var(--lp-text-muted)]">.ai</span>
              </span>
            </Link>
            <p id="footer-tagline" className="text-sm text-[var(--lp-text-secondary)] leading-relaxed mb-6">
              Structured interview intelligence for hiring teams that decide with evidence.
            </p>

          </div>

          <div id="footer-product" className="md:col-span-1">
            <p id="footer-product-heading" className="text-sm font-medium text-[var(--lp-text-primary)] mb-4">
              Product
            </p>
            <ul className="space-y-3">
              <li>
                <Link href="/onboarding" id="footer-link-get-started" onClick={() => trackEvent("nav_link_clicked", { link_name: "Get Started", destination: "/onboarding", location: "footer" })} className="text-sm text-[var(--lp-text-secondary)] hover:text-[var(--lp-text-primary)] transition-colors">
                  Get Started
                </Link>
              </li>
              <li>
                <Link href="/login" id="footer-link-login" onClick={() => trackEvent("nav_link_clicked", { link_name: "Login", destination: "/login", location: "footer" })} className="text-sm text-[var(--lp-text-secondary)] hover:text-[var(--lp-text-primary)] transition-colors">
                  Login
                </Link>
              </li>
              <li>
                <Link
                  href="/blogs"
                  id="footer-link-blog"
                  onClick={() => trackEvent("nav_link_clicked", { link_name: "Blog", destination: "/blogs", location: "footer" })}
                  className="text-sm text-[var(--lp-text-secondary)] hover:text-[var(--lp-text-primary)] transition-colors"
                >
                  Blog
                </Link>
              </li>
            </ul>
          </div>


          <div id="footer-legal" className="md:col-span-1">
            <p id="footer-legal-heading" className="text-sm font-medium text-[var(--lp-text-primary)] mb-4">
              Legal
            </p>
            <ul className="space-y-3">
              <li>
                <Link
                  href="/terms"
                  id="footer-terms-link"
                  className="text-sm text-[var(--lp-text-secondary)] hover:text-[var(--lp-text-primary)] transition-colors"
                >
                  Terms of Service
                </Link>
              </li>
              <li>
                <Link
                  href="/privacy"
                  id="footer-privacy-link"
                  className="text-sm text-[var(--lp-text-secondary)] hover:text-[var(--lp-text-primary)] transition-colors"
                >
                  Privacy Policy
                </Link>
              </li>
            </ul>
          </div>
        </div>

        <div id="footer-bottom" className="mt-12 pt-6 border-t border-[var(--lp-border)]">
          <p id="footer-copyright" className="text-xs text-[var(--lp-text-faint)] text-center">
            &copy; {new Date().getFullYear()} OpenRecruiting contributors. Open source under the Apache License 2.0.
          </p>
        </div>
      </div>

    </footer>
  );
}

export { Footer };
