'use client';

import { usePathname } from 'next/navigation';
import { type ReactNode, useEffect, useRef } from 'react';
import { LAUNCH_HIDE_SHOW_EARLIER } from '@/lib/launch-flags';
import { useSessionStore, useShellStore } from '@/stores';
import type { ChatTabId } from '@/types';
import { Composer } from './composer';
import { LoadPreviousPill } from './load-previous-pill';

interface ChatColumnProps {
  id: string;
  children: ReactNode;
}

export function ChatColumn({ id, children }: ChatColumnProps) {
  const activeTabId = useShellStore((s) => s.activeTabId);
  const mode = useShellStore((s) => s.mode());
  const agentId: ChatTabId = activeTabId ?? 'home';
  const isAgentic = mode === 'agentic' || mode === 'home';
  const pathname = usePathname();
  // The intake agent owns its full canvas — the bento hub and the session
  // shell provide their own composer/affordances and a 940px layout. So the
  // shell's chat composer and the 760px max-width clamp are suppressed on every
  // /intake route; the design has no bottom chat bar there.
  const isIntake = (pathname ?? '').startsWith('/intake');

  const lastMsgId = useSessionStore((s) => {
    const msgs = s.sessions[agentId]?.messages ?? [];
    return msgs[msgs.length - 1]?.id ?? null;
  });
  // Streaming token updates mutate the LAST message's text in place — the id
  // never changes, so keying scroll only on id would freeze the view while the
  // agent streams. Tracking the tail message's length retriggers the scroll on
  // every appended token.
  const lastMsgLen = useSessionStore((s) => {
    const msgs = s.sessions[agentId]?.messages ?? [];
    return msgs[msgs.length - 1]?.text.length ?? 0;
  });
  const earlierCursor = useSessionStore((s) => {
    const sel = s.sessions[agentId]?.selections ?? {};
    return Number(sel.earlierCursor ?? 0);
  });
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: lastMsgLen is an intentional re-scroll trigger for in-place streaming growth, not a value read in the body
  useEffect(() => {
    // Stick-to-bottom is chat-transcript behaviour (home + sub-agent tabs). Rail
    // views (qna mode) render an ordinary top-anchored page in this same
    // container, so auto-scrolling them to the bottom hides their header.
    if (!isAgentic) return;
    if (!lastMsgId) return;
    const el = scrollRef.current;
    if (!el) return;
    // Scroll on a new tail (append) AND on in-place growth of the tail message
    // (streaming). loadEarlier prepends so neither id nor tail length change,
    // and that path is handled by the earlierCursor effect below.
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }, [lastMsgId, lastMsgLen, isAgentic]);

  // Belt-and-suspenders: a ResizeObserver on the transcript CONTENT catches any
  // height growth the text-length heuristic misses (rich cards, images, async
  // content). The scroll container itself is fixed-height (flex-1), so we must
  // observe its growing child, then pin the container to the bottom.
  // biome-ignore lint/correctness/useExhaustiveDependencies: isIntake is an intentional re-attach trigger; the observed inner wrapper only exists off the /intake route
  useEffect(() => {
    // Same as above: only pin chat surfaces to the bottom. For rail views this
    // observer would fire as their list data loads in and shove the header off.
    if (!isAgentic) return;
    const scroll = scrollRef.current;
    const content = contentRef.current;
    if (!scroll || !content || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => {
      scroll.scrollTo({ top: scroll.scrollHeight, behavior: 'smooth' });
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, [isIntake, isAgentic]);

  useEffect(() => {
    if (earlierCursor === 0) return;
    const el = scrollRef.current;
    if (!el) return;
    // SHOW EARLIER prepended history above the greeting; bring the newly
    // loaded messages into view by scrolling the container to the top.
    el.scrollTo({ top: 0, behavior: 'smooth' });
  }, [earlierCursor]);

  // This container lives in the persistent (shell) layout, so its scroll offset
  // survives client-side navigation. Chat surfaces re-pin to the bottom via the
  // effects above; rail views (qna mode) are plain pages, so reset them to the
  // top on each route change instead of inheriting a prior transcript's offset.
  // biome-ignore lint/correctness/useExhaustiveDependencies: pathname is the intentional re-run trigger (route change → reset to top), not a value read in the body
  useEffect(() => {
    if (isAgentic) return;
    scrollRef.current?.scrollTo({ top: 0, behavior: 'instant' });
  }, [pathname, isAgentic]);

  return (
    <section id={id} aria-label="OpenRecruiting chat" className="flex min-h-0 min-w-0 flex-col bg-bg">
      <div
        id={`${id}-scroll`}
        ref={scrollRef}
        className={`scrollable flex-1 [scrollbar-gutter:stable] ${
          isIntake ? '' : 'px-4 pt-2 pb-4 sm:px-8'
        }`}
        style={{ scrollBehavior: 'smooth' }}
      >
        {isIntake ? (
          children
        ) : (
          <div
            id={`${id}-inner`}
            ref={contentRef}
            className="mx-auto flex w-full max-w-[760px] flex-col gap-3 pb-6"
          >
            {isAgentic && !LAUNCH_HIDE_SHOW_EARLIER && (
              <LoadPreviousPill id={`${id}-load-prev`} agentId={agentId} />
            )}
            {children}
          </div>
        )}
      </div>
      {!isIntake && (
        <div id={`${id}-composer-wrap`} className="bg-bg px-4 py-3 sm:px-8 sm:py-4">
          <div className="mx-auto w-full max-w-[880px]">
            <Composer id={`${id}-composer`} />
          </div>
        </div>
      )}
    </section>
  );
}
