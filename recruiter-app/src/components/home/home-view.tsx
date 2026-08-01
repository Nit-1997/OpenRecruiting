'use client';

import {
  ArrowRight,
  Brain,
  Briefcase,
  ClipboardCheck,
  type FileText,
  LineChart,
  ListChecks,
  Mic,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo } from 'react';
import { BrandIcon } from '@/components/icons/brand-icons';
import { TranscriptTail } from '@/components/shell/primitives';
import { useProfile } from '@/hooks/use-services';
import { useShellSync } from '@/hooks/use-shell-sync';
import { routeChip } from '@/lib/home-route';
import { isSubAgentComingSoon, LAUNCH_HIDE_HOME_STATUS_WIDGET } from '@/lib/launch-flags';
import { cn } from '@/lib/utils';
import { useComposerStore, useSessionStore } from '@/stores';

interface HomeViewProps {
  id: string;
}

type TabId = 'intake' | 'sourcing' | 'debrief' | 'brain';

const ACTIONS: Array<{
  tabId: TabId;
  title: string;
  sub: string;
  meta: string;
  Icon: typeof Mic;
}> = [
  {
    tabId: 'intake',
    title: 'Create a new role',
    sub: 'Talk through scope, comp, scorecard — OpenRecruiting drafts the requisition.',
    meta: '2 min call',
    Icon: Mic,
  },
  {
    tabId: 'debrief',
    title: 'Debrief a role',
    sub: 'Pick role, pick candidates, start debrief — packet on the right.',
    meta: '3 ready',
    Icon: ClipboardCheck,
  },
  {
    tabId: 'brain',
    title: 'Insights & brain',
    sub: 'Knowledge graph across your pipeline. Ask anything.',
    meta: 'Live',
    Icon: Brain,
  },
];

interface QuickStart {
  id: string;
  title: string;
  sub: string;
  // A card either points at a sub-agent tab (/{tabId}, subject to coming-soon
  // gating) or at an explicit route via href. href takes precedence.
  tabId?: TabId;
  href?: string;
  Icon: typeof FileText;
}

const QUICK_STARTS: QuickStart[] = [
  {
    id: 'browse-roles',
    title: 'Browse open roles',
    sub: 'Jump to your roles board.',
    href: '/view/roles',
    Icon: Briefcase,
  },
  {
    id: 'market-comp',
    title: 'Market comp snapshot',
    sub: 'See real-time market benchmarks.',
    tabId: 'brain',
    Icon: LineChart,
  },
  {
    id: 'interview-plan',
    title: 'Interview plan builder',
    sub: 'Create a role-specific interview plan.',
    tabId: 'intake',
    Icon: ListChecks,
  },
];

function getGreeting(): string {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
}

function StatusWidget({ id }: { id: string }) {
  return (
    <div
      id={id}
      className="flex shrink-0 items-center gap-3 rounded-[14px] border border-border/70 bg-white/75 px-4 py-3 shadow-[0_1px_2px_rgba(0,0,0,0.02)] backdrop-blur-sm"
    >
      <svg
        role="img"
        aria-label="Sparkline showing stable activity"
        viewBox="0 0 64 24"
        className="h-6 w-16 shrink-0 text-text-muted"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <title>Sparkline showing stable activity</title>
        <path d="M2 16 C 8 16, 12 6, 18 10 S 28 22, 34 14 S 46 4, 52 8 S 60 14, 62 12" />
      </svg>
      <div className="flex min-w-0 flex-col">
        <span className="font-medium text-[13px] text-text-primary leading-tight">
          Everything looks good
        </span>
        <span className="truncate font-mono text-[10px] text-text-muted uppercase tracking-[0.14em]">
          3 debriefs ready · 6 active roles
        </span>
      </div>
      <ArrowRight aria-hidden strokeWidth={1.75} className="h-3.5 w-3.5 shrink-0 text-text-faint" />
    </div>
  );
}

export function HomeView({ id }: HomeViewProps) {
  useShellSync();
  const router = useRouter();
  const { data: profile } = useProfile();
  const firstName = profile?.name?.trim().split(/\s+/)[0];
  const setHomeScope = useComposerStore((s) => s.setHomeScope);
  const homeStartedAt = useSessionStore((s) => s.sessions.home?.startedAt ?? null);
  const greetingTs = useMemo(
    () => (homeStartedAt ? Date.parse(homeStartedAt) : Date.now()),
    [homeStartedAt],
  );
  useEffect(() => {
    setHomeScope();
  }, [setHomeScope]);

  const onChip = (c: { value: string }) => {
    routeChip(router, c.value);
  };

  return (
    <div id={`${id}-wrap`} className="flex flex-col gap-3">
      <TranscriptTail id={`${id}-history`} tabId="home" until={greetingTs} onChip={onChip} />
      <div id={id} className="flex items-start gap-3.5 pt-1 pb-1">
        <div
          id={`${id}-avatar`}
          aria-hidden
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white"
        >
          <BrandIcon className="h-6 w-6 text-text-primary" />
        </div>
        <div id={`${id}-body`} className="min-w-0 flex-1">
          <div id={`${id}-head`} className="flex flex-wrap items-start justify-between gap-4 pb-5">
            <div className="min-w-0 flex-1">
              <div
                id={`${id}-brief`}
                className="mb-2 inline-flex items-center gap-2 font-mono text-[11px] text-text-faint uppercase tracking-[0.18em]"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-text-muted" />
                <span>
                  OpenRecruiting ·{' '}
                  {new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
                  {' · Today, '}
                  {new Date().toLocaleDateString('en-US', { weekday: 'long' })}
                </span>
              </div>
              <h1
                id={`${id}-title`}
                className="mb-2 font-display font-normal text-[28px] leading-[1.05] tracking-[-0.015em] sm:text-[38px]"
              >
                {getGreeting()}
                {firstName ? (
                  <>
                    , <em className="text-text-secondary">{firstName}.</em>
                  </>
                ) : (
                  '.'
                )}{' '}
                <span className="text-text-secondary">What are we working on?</span>
              </h1>
              <p
                id={`${id}-sub`}
                className="max-w-[560px] text-[15px] text-text-secondary leading-[1.55]"
              >
                Pick a flow below — or just type what you want to do.
              </p>
            </div>
            {!LAUNCH_HIDE_HOME_STATUS_WIDGET && <StatusWidget id={`${id}-status`} />}
          </div>

          <div
            id={`${id}-actions`}
            className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4"
          >
            {ACTIONS.map((a) => {
              const comingSoon = isSubAgentComingSoon(a.tabId);
              return (
                <button
                  key={a.tabId}
                  id={`${id}-action-${a.tabId}`}
                  type="button"
                  disabled={comingSoon}
                  aria-disabled={comingSoon || undefined}
                  title={comingSoon ? 'Coming soon' : undefined}
                  onClick={comingSoon ? undefined : () => router.push(`/${a.tabId}`)}
                  className={cn(
                    'group relative flex min-h-[160px] flex-col gap-2.5 overflow-hidden rounded-[16px] border border-border/70 bg-white/75 p-4 text-left shadow-[0_1px_2px_rgba(0,0,0,0.02)] backdrop-blur-sm transition-all',
                    comingSoon
                      ? 'cursor-not-allowed opacity-70'
                      : 'hover:border-text-primary/40 hover:bg-white/95 hover:shadow-[0_4px_16px_rgba(0,0,0,0.04)]',
                  )}
                >
                  <div className="flex h-[34px] w-[34px] items-center justify-center rounded-[10px] border border-border/60 bg-white/70 text-text-primary">
                    <a.Icon strokeWidth={1.75} className="h-[17px] w-[17px]" />
                  </div>
                  <h3 className="font-medium font-sans text-[16px] leading-tight tracking-tight">
                    {a.title}
                  </h3>
                  <p className="text-[13px] text-text-muted leading-[1.45]">{a.sub}</p>
                  <div className="mt-auto flex items-center justify-between gap-2">
                    {comingSoon ? (
                      <span className="rounded-full border border-border bg-white px-2 py-0.5 font-mono text-[9px] text-text-muted uppercase tracking-[0.14em]">
                        Coming soon
                      </span>
                    ) : (
                      <>
                        <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
                          {a.meta}
                        </span>
                        <ArrowRight
                          aria-hidden
                          strokeWidth={1.75}
                          className="h-3.5 w-3.5 text-text-faint transition group-hover:translate-x-0.5 group-hover:text-text-primary"
                        />
                      </>
                    )}
                  </div>
                </button>
              );
            })}
          </div>

          <section id={`${id}-quick`} className="mt-7 flex flex-col gap-3">
            <div className="flex items-end justify-between gap-3">
              <div className="flex min-w-0 flex-col">
                <span className="font-medium font-sans text-[15px] text-text-primary leading-tight">
                  Suggested for you
                </span>
                <span className="font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
                  Quick starts based on your past activity
                </span>
              </div>
            </div>
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
              {QUICK_STARTS.map((q) => {
                const comingSoon = q.tabId ? isSubAgentComingSoon(q.tabId) : false;
                const target = q.href ?? (q.tabId ? `/${q.tabId}` : undefined);
                return (
                  <button
                    key={q.id}
                    id={`${id}-quick-${q.id}`}
                    type="button"
                    disabled={comingSoon}
                    aria-disabled={comingSoon || undefined}
                    title={comingSoon ? 'Coming soon' : undefined}
                    onClick={comingSoon || !target ? undefined : () => router.push(target)}
                    className={cn(
                      'group flex items-center gap-3 rounded-[14px] border border-border/70 bg-white/75 p-3.5 text-left shadow-[0_1px_2px_rgba(0,0,0,0.02)] backdrop-blur-sm transition-all',
                      comingSoon
                        ? 'cursor-not-allowed opacity-70'
                        : 'hover:border-text-primary/40 hover:bg-white/95 hover:shadow-[0_2px_10px_rgba(0,0,0,0.04)]',
                    )}
                  >
                    <div className="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-[10px] border border-border/60 bg-white/70 text-text-primary">
                      <q.Icon strokeWidth={1.75} className="h-[16px] w-[16px]" />
                    </div>
                    <div className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate font-medium font-sans text-[13.5px] text-text-primary leading-tight">
                        {q.title}
                      </span>
                      <span className="truncate text-[12px] text-text-muted leading-tight">
                        {q.sub}
                      </span>
                    </div>
                    {comingSoon ? (
                      <span className="shrink-0 rounded-full border border-border bg-white px-2 py-0.5 font-mono text-[9px] text-text-muted uppercase tracking-[0.14em]">
                        Coming soon
                      </span>
                    ) : (
                      <ArrowRight
                        aria-hidden
                        strokeWidth={1.75}
                        className="h-3.5 w-3.5 shrink-0 text-text-faint transition group-hover:translate-x-0.5 group-hover:text-text-primary"
                      />
                    )}
                  </button>
                );
              })}
            </div>
          </section>
        </div>
      </div>
      <TranscriptTail id={`${id}-post`} tabId="home" since={greetingTs} onChip={onChip} />
    </div>
  );
}
