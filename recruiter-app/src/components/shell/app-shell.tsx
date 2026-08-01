'use client';

import { Loader2 } from 'lucide-react';
import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';
import { useEffect, useState } from 'react';
import { useKeyboardShortcuts } from '@/hooks/use-keyboard-shortcuts';
import { registerSeedFactory } from '@/services';
import { useAuthStore, useShellStore, useVoiceStore } from '@/stores';

import { RightRail } from './right-rail';
import { SplitShell } from './split-shell';
import { TopBar } from './top-bar';
import { VoicePopout } from './voice-popout';

interface AppShellProps {
  id: string;
  children: ReactNode;
}

export function AppShell({ id, children }: AppShellProps) {
  const mode = useShellStore((s) => s.mode());
  const voiceActive = useVoiceStore((s) => s.active);
  const voiceMinimized = useVoiceStore((s) => s.minimized);
  const minimizeVoice = useVoiceStore((s) => s.minimize);

  const authed = useAuthStore((s) => s.authed);
  // `initialized` flips true only after the first session check resolves. We
  // MUST NOT redirect before then, or we bounce an authenticated user to the
  // login app mid-hydration → infinite loop with landing.
  const initialized = useAuthStore((s) => s.initialized);
  const pathname = usePathname();
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setHydrated(true);
    // Register the localStorage mock seed ONLY in the opt-out test/demo path
    // (NEXT_PUBLIC_V2_API=false). In production (v2 enabled) this is a no-op,
    // so no service can silently fall back to fabricated seed data — a missed
    // mock-only branch surfaces as an empty/error state instead. (FE-F5)
    registerSeedFactory();
  }, []);

  useEffect(() => {
    if (!hydrated || !initialized) return;
    if (!authed) {
      // Single login surface is landing (shared openrecruiting-auth cookie). Use a
      // full-page nav (cross-origin) rather than router.replace. Middleware is
      // the primary gate; this is the client-side backstop.
      const landing = process.env.NEXT_PUBLIC_LANDING_URL || 'http://localhost:3000';
      const redirect =
        pathname && pathname !== '/' ? `?redirect=${encodeURIComponent(pathname)}` : '';
      window.location.href = `${landing}/login${redirect}`;
    }
  }, [authed, initialized, hydrated, pathname]);

  useKeyboardShortcuts();

  useEffect(() => {
    if (mode === 'qna' && voiceActive && !voiceMinimized) {
      minimizeVoice();
    }
  }, [mode, voiceActive, voiceMinimized, minimizeVoice]);

  if (!hydrated || !authed) {
    return (
      <div
        id={`${id}-gate`}
        className="flex h-screen w-screen items-center justify-center bg-bg text-text-muted"
      >
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    );
  }

  return (
    <div
      id={id}
      className="relative flex h-screen w-screen overflow-hidden bg-bg text-text-primary"
    >
      <div id={`${id}-main`} className="flex min-h-0 min-w-0 flex-1 flex-col">
        <TopBar id={`${id}-topbar`} />
        <div id={`${id}-body`} className="flex min-h-0 flex-1">
          <SplitShell id={`${id}-shell`}>{children}</SplitShell>
        </div>
      </div>
      <RightRail id={`${id}-rail`} />
      <VoicePopout id={`${id}-voice`} />
    </div>
  );
}
