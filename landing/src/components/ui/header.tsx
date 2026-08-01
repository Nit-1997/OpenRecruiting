"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { Menu, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAnalytics } from "@/hooks/useAnalytics";
import dynamic from "next/dynamic";

const CalendlyModal = dynamic(
  () => import("@/components/ui/calendly-modal").then((mod) => ({ default: mod.CalendlyModal })),
  { ssr: false },
);

function Header({ variant = "hero" }: { variant?: "hero" | "light" }) {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const [showCalendly, setShowCalendly] = useState(false);
  const pathname = usePathname();
  const isHomePage = pathname === "/";

  const { trackEvent } = useAnalytics();
  const [pastFirstFold, setPastFirstFold] = useState(false);

  useEffect(() => {
    const onScroll = () => {
      setScrolled(window.scrollY > 50);
      setPastFirstFold(window.scrollY > window.innerHeight * 0.8);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const isDark = variant === "hero" && !scrolled;
  const showBookDemo = !isHomePage || pastFirstFold;

  return (
    <>
      <header
        id="main-header"
        className="fixed top-0 left-0 right-0 z-50 flex justify-center pointer-events-none"
      >
        <nav
          id="header-nav-pill"
          className={`pointer-events-auto transition-all duration-500 ease-out flex items-center border ${
            scrolled
              ? "mt-2 px-3 xl:px-4 h-12 xl:h-14 rounded-full max-w-xl xl:max-w-2xl gap-1 xl:gap-2"
              : "mt-4 px-5 xl:px-8 h-14 xl:h-16 rounded-full max-w-3xl xl:max-w-4xl gap-3 xl:gap-5"
          } ${
            isDark
              ? "bg-white/[0.08] backdrop-blur-xl border-white/[0.12] shadow-[0_8px_32px_rgba(0,0,0,0.4)]"
              : "bg-white/60 backdrop-blur-xl border-white/40 shadow-[0_8px_32px_rgba(0,0,0,0.08)]"
          }`}
        >
          <Link href="/" id="header-logo" className="flex items-center gap-2 shrink-0">
            <Image
              id="logo-icon"
              src="/zymo-logo.svg"
              alt="OpenRecruiting Logo"
              width={32}
              height={32}
              className={`transition-all duration-500 ${
                scrolled ? "w-7 h-7 xl:w-8 xl:h-8" : "w-8 h-8 xl:w-9 xl:h-9"
              } ${isDark ? "invert" : ""}`}
            />
            <span
              id="logo-text"
              className={`tracking-tight font-[family-name:var(--font-pacifico)] transition-all duration-500 ${
                scrolled ? "text-base xl:text-lg" : "text-lg xl:text-xl"
              } ${isDark ? "text-white" : "text-[#111111]"}`}
            >
              <span>openrecruiting</span>
              <span className={isDark ? "text-white/60" : "text-[#111111]"}>.ai</span>
            </span>
          </Link>

          <div id="header-nav-links" className="hidden md:flex items-center flex-1 justify-center gap-1 xl:gap-2">
            <Link
              id="product-link-desktop"
              href="/#from-plan-to-decision"
              onClick={() => trackEvent("nav_link_clicked", { link_name: "Product", destination: "/#from-plan-to-decision", location: "header" })}
              className={`px-3 xl:px-4 py-1.5 rounded-full transition-all duration-300 font-medium ${
                scrolled ? "text-xs xl:text-sm" : "text-sm xl:text-base"
              } ${
                isDark
                  ? "text-white/80 hover:text-white hover:bg-white/10"
                  : "text-[#111111]/70 hover:text-[#111111] hover:bg-black/5"
              }`}
            >
              Product
            </Link>
            <Link
              id="blog-link-desktop"
              href="/blogs"
              onClick={() => trackEvent("nav_link_clicked", { link_name: "Blog", destination: "/blogs", location: "header" })}
              className={`px-3 xl:px-4 py-1.5 rounded-full transition-all duration-300 font-medium ${
                scrolled ? "text-xs xl:text-sm" : "text-sm xl:text-base"
              } ${
                isDark
                  ? "text-white/80 hover:text-white hover:bg-white/10"
                  : "text-[#111111]/70 hover:text-[#111111] hover:bg-black/5"
              }`}
            >
              Blog
            </Link>
            <Link
              id="cortex-link-desktop"
              href="/cortex"
              onClick={() => trackEvent("nav_link_clicked", { link_name: "Cortex", destination: "/cortex", location: "header" })}
              className={`px-3 xl:px-4 py-1.5 rounded-full transition-all duration-300 font-medium ${
                scrolled ? "text-xs xl:text-sm" : "text-sm xl:text-base"
              } ${
                isDark
                  ? "text-white/80 hover:text-white hover:bg-white/10"
                  : "text-[#111111]/70 hover:text-[#111111] hover:bg-black/5"
              }`}
            >
              Cortex
            </Link>
          </div>

          <div id="header-nav-actions-desktop" className="hidden md:flex items-center gap-2 shrink-0">
            <Link href="/login">
              <Button
                id="login-btn-desktop"
                variant={showBookDemo ? "ghost" : "default"}
                className={`rounded-full transition-all duration-500 ${
                  scrolled
                    ? "h-8 xl:h-9 px-4 xl:px-5 text-xs xl:text-sm"
                    : "h-9 xl:h-10 px-5 xl:px-6 text-sm xl:text-base"
                } ${
                  showBookDemo
                    ? isDark
                      ? "text-white/80 hover:text-white hover:bg-white/10"
                      : "text-[#111111]/70 hover:text-[#111111] hover:bg-black/5"
                    : isDark
                      ? "bg-white text-[#111111] hover:bg-white/90"
                      : "bg-[#111111] text-white hover:bg-[#111111]/90"
                } ${showBookDemo ? "" : "font-medium"}`}
              >
                Login
              </Button>
            </Link>
            {showBookDemo && (
              <Button
                id="book-demo-btn-desktop"
                onClick={() => { trackEvent("demo_booking_opened", { cta_location: "header" }); setShowCalendly(true); }}
                className={`rounded-full font-medium transition-all duration-500 ${
                  scrolled
                    ? "h-8 xl:h-9 px-4 xl:px-5 text-xs xl:text-sm"
                    : "h-9 xl:h-10 px-5 xl:px-6 text-sm xl:text-base"
                } ${
                  isDark
                    ? "bg-white text-[#111111] hover:bg-white/90"
                    : "bg-[#111111] text-white hover:bg-[#111111]/90"
                }`}
              >
                Book Demo
              </Button>
            )}
          </div>

          <div id="mobile-nav-actions" className="flex md:hidden items-center ml-auto">
            <Button
              id="mobile-menu-btn"
              variant="ghost"
              size="icon"
              className={`h-9 w-9 rounded-full transition-colors duration-300 ${
                isDark ? "text-white hover:bg-white/10" : "text-[#111111] hover:bg-black/5"
              }`}
              onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
            >
              {isMobileMenuOpen ? (
                <X id="mobile-menu-close-icon" className="h-5 w-5" />
              ) : (
                <Menu id="mobile-menu-open-icon" className="h-5 w-5" />
              )}
              <span className="sr-only">Toggle menu</span>
            </Button>
          </div>
        </nav>

        {isMobileMenuOpen && (
          <div
            id="header-mobile-dropdown"
            className="pointer-events-auto absolute top-full left-1/2 -translate-x-1/2 mt-2 w-[calc(100%-2rem)] max-w-md rounded-2xl bg-white/70 backdrop-blur-xl border border-white/40 shadow-[0_8px_32px_rgba(0,0,0,0.12)] md:hidden"
          >
            <div className="px-4 py-3 flex flex-col gap-1">
              <Link
                id="product-link-mobile"
                href="/#from-plan-to-decision"
                onClick={() => { trackEvent("nav_link_clicked", { link_name: "Product", destination: "/#from-plan-to-decision", location: "header" }); setIsMobileMenuOpen(false); }}
                className="w-full h-11 flex items-center px-4 text-[#111111] text-sm font-medium hover:bg-black/5 rounded-xl"
              >
                Product
              </Link>
              <Link
                id="blog-link-mobile"
                href="/blogs"
                onClick={() => { trackEvent("nav_link_clicked", { link_name: "Blog", destination: "/blogs", location: "header" }); setIsMobileMenuOpen(false); }}
                className="w-full h-11 flex items-center px-4 text-[#111111] text-sm font-medium hover:bg-black/5 rounded-xl"
              >
                Blog
              </Link>
              <Link
                id="cortex-link-mobile"
                href="/cortex"
                onClick={() => { trackEvent("nav_link_clicked", { link_name: "Cortex", destination: "/cortex", location: "header" }); setIsMobileMenuOpen(false); }}
                className="w-full h-11 flex items-center px-4 text-[#111111] text-sm font-medium hover:bg-black/5 rounded-xl"
              >
                Cortex
              </Link>
              <Link href="/login" onClick={() => setIsMobileMenuOpen(false)}>
                <Button
                  id="login-btn-mobile"
                  variant={showBookDemo ? "ghost" : "default"}
                  className={showBookDemo
                    ? "w-full h-11 justify-start text-[#111111] rounded-xl hover:bg-black/5"
                    : "w-full h-11 bg-[#111111] text-white rounded-full mt-1"
                  }
                >
                  Login
                </Button>
              </Link>
              {showBookDemo && (
                <Button
                  id="book-demo-btn-mobile"
                  className="w-full h-11 bg-[#111111] text-white rounded-full mt-1"
                  onClick={() => { trackEvent("demo_booking_opened", { cta_location: "header" }); setIsMobileMenuOpen(false); setShowCalendly(true); }}
                >
                  Book Demo
                </Button>
              )}
            </div>
          </div>
        )}
      </header>

      {showCalendly && (
        <CalendlyModal
          isOpen={showCalendly}
          onClose={() => setShowCalendly(false)}
        />
      )}
    </>
  );
}

export { Header };
