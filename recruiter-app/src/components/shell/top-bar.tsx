'use client';

import { Brain, ClipboardCheck, Mic } from 'lucide-react';
import { usePathname, useRouter } from 'next/navigation';
import { type ComponentType, type KeyboardEvent, useRef } from 'react';
import { BrandIcon } from '@/components/icons/brand-icons';
import { isSubAgentComingSoon } from '@/lib/launch-flags';
import { cn } from '@/lib/utils';
import { useShellStore } from '@/stores';
import type { SubAgentId } from '@/types';
import { SUB_AGENT_LABELS } from '@/types';

interface TopBarProps {
  id: string;
}

interface TabDefinition {
  id: SubAgentId;
  label: string;
  Icon: ComponentType<{ className?: string; strokeWidth?: number }>;
}

// Only surface the agents that actually drive action. manage (Requisition)
// and packets (Feedback) were read-only wrappers around data that already
// lives inside role detail + artifacts — they don't belong in the hub.
// debrief + brain are shown but disabled ("Coming soon", see launch-flags)
// until their flows ship; the tab defs + flow code are retained.
const TAB_ORDER: TabDefinition[] = [
  { id: 'intake', label: SUB_AGENT_LABELS.intake, Icon: Mic },
  { id: 'debrief', label: SUB_AGENT_LABELS.debrief, Icon: ClipboardCheck },
  { id: 'brain', label: SUB_AGENT_LABELS.brain, Icon: Brain },
];

export function TopBar({ id }: TopBarProps) {
  const router = useRouter();
  const pathname = usePathname();
  const activeTabId = useShellStore((s) => s.activeTabId);
  const listRef = useRef<HTMLDivElement | null>(null);

  const isHome = pathname === '/';
  const activeId: SubAgentId | null = isHome ? null : (activeTabId ?? null);

  const onTabKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    const buttons = Array.from(
      listRef.current?.querySelectorAll<HTMLButtonElement>('button[role="tab"]') ?? [],
    );
    if (buttons.length === 0) return;
    const focused = document.activeElement as HTMLButtonElement | null;
    const idx = focused ? buttons.indexOf(focused) : -1;
    const next =
      e.key === 'ArrowLeft'
        ? idx <= 0
          ? buttons.length - 1
          : idx - 1
        : idx === buttons.length - 1
          ? 0
          : idx + 1;
    e.preventDefault();
    buttons[next]?.focus();
  };

  const navigate = (tabId: SubAgentId) => {
    router.push(`/${tabId}`);
  };

  return (
    <header id={id} className="relative z-30 flex h-16 items-center bg-bg px-4 sm:px-8">
      <div
        id={`${id}-rail`}
        className="mx-auto flex w-full max-w-[880px] items-center justify-center overflow-x-auto"
      >
        <div
          id={`${id}-pill`}
          className="inline-flex h-14 shrink-0 items-center gap-2 rounded-full border border-border bg-white px-3 shadow-[0_4px_18px_rgba(0,0,0,0.04)] sm:gap-4 sm:px-5"
        >
          <button
            id={`${id}-brand`}
            type="button"
            onClick={() => router.push('/')}
            aria-current={isHome ? 'page' : undefined}
            className="inline-flex items-center gap-2 leading-none text-text-primary transition-opacity hover:opacity-80"
            aria-label="OpenRecruiting home"
          >
            <BrandIcon id={`${id}-brand-icon`} className="h-[22px] w-[22px] shrink-0" />
            <span
              id={`${id}-brand-stack`}
              className="hidden flex-col items-start gap-1 sm:inline-flex"
            >
              {/* Pacifico's content area is 1.756em (ascent 1.303 + descent 0.453), so a
                  1:1 line-height spilled the p/g descenders ~7.5px below the box and into
                  the caption. 36px contains the glyphs, making the gap below a real gap. */}
              <span
                id={`${id}-brand-word`}
                className="font-brand text-[20px] leading-[36px] tracking-tight"
              >
                openrecruiting<span className="text-text-muted">.ai</span>
              </span>
              <span
                id={`${id}-brand-caption`}
                className={cn(
                  'font-mono text-[9px] uppercase leading-none tracking-[0.22em]',
                  isHome ? 'text-text-primary' : 'text-text-faint',
                )}
              >
                Agent Hub
              </span>
            </span>
          </button>
          <div
            id={`${id}-tabs`}
            ref={listRef}
            role="tablist"
            aria-label="OpenRecruiting tabs"
            onKeyDown={onTabKeyDown}
            className="inline-flex items-center gap-1"
          >
            {TAB_ORDER.map((t) => {
              const comingSoon = isSubAgentComingSoon(t.id);
              const active = !comingSoon && activeId === t.id;
              const Icon = t.Icon;
              return (
                <button
                  key={t.id}
                  id={`${id}-tab-${t.id}`}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  aria-disabled={comingSoon || undefined}
                  disabled={comingSoon}
                  title={comingSoon ? 'Coming soon' : undefined}
                  tabIndex={active ? 0 : -1}
                  onClick={comingSoon ? undefined : () => navigate(t.id)}
                  className={cn(
                    'inline-flex h-9 items-center gap-1.5 rounded-full px-2.5 font-medium text-[13.5px] transition-colors sm:px-4',
                    comingSoon
                      ? 'cursor-not-allowed text-text-faint'
                      : active
                        ? 'bg-text-primary text-white shadow-sm'
                        : 'text-text-secondary hover:bg-surface hover:text-text-primary',
                  )}
                  aria-label={comingSoon ? `${t.label} (coming soon)` : t.label}
                >
                  <Icon strokeWidth={1.75} className="h-3.5 w-3.5 shrink-0" />
                  <span className="hidden sm:inline">{t.label}</span>
                  {comingSoon && (
                    <span className="hidden rounded-full border border-border bg-white px-1.5 py-0.5 font-mono text-[8.5px] text-text-muted uppercase tracking-[0.12em] sm:inline-flex">
                      Coming soon
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </header>
  );
}
