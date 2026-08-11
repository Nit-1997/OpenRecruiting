"use client";

import { useEffect, useState, Suspense } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import posthog from "posthog-js";
import { PostHogProvider as PHProvider } from "posthog-js/react";
import { getRuntimeConfig } from "@/lib/runtime-config";

function PostHogPageView() {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (!pathname || !posthog.__loaded) return;
    let url = window.origin + pathname;
    if (searchParams.toString()) {
      url = url + "?" + searchParams.toString();
    }
    posthog.capture("$pageview", { $current_url: url });
  }, [pathname, searchParams]);

  return null;
}

export function PostHogProvider({ children }: { children: React.ReactNode }) {
  const [initialized, setInitialized] = useState(false);

  useEffect(() => {
    const { posthogKey, posthogHost } = getRuntimeConfig();
    if (!posthogKey) return;

    posthog.init(posthogKey, {
      api_host: posthogHost || "https://us.i.posthog.com",
      capture_pageview: false,
      capture_pageleave: true,
      cross_subdomain_cookie: true,
      loaded: () => setInitialized(true),
    });

    if (!initialized) setInitialized(true);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <PHProvider client={posthog}>
      <Suspense fallback={null}>
        <PostHogPageView />
      </Suspense>
      {children}
    </PHProvider>
  );
}
