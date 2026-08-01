'use client';

import { Briefcase, Quote as QuoteIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { useTypedArtifact } from '../_shared/use-artifact-data';
import type {
  CortexClusterBar,
  CortexPanelistMixViz,
  CortexQuoteCard,
  CortexSignalCard,
  CortexSilverCandidate,
  CortexSplitBarViz,
  CortexTimelineViz,
} from './types';

export interface CortexAnalysisArtifactProps {
  id: string;
  artifactId: string;
  onDraftNote?: (candidateId: string) => void;
  onDraftAll?: () => void;
}

export function CortexAnalysisArtifact({
  id,
  artifactId,
  onDraftNote,
  onDraftAll,
}: CortexAnalysisArtifactProps) {
  const artifact = useTypedArtifact(artifactId, 'cortex-analysis');
  if (!artifact) return null;
  const data = artifact.data;
  if (!data?.signals) {
    return (
      <div id={id} className="animate-pulse pt-2 text-[12.5px] text-text-muted">
        Cortex is composing the analysis…
      </div>
    );
  }

  return (
    <div id={id} key={artifactId} className="cortex-blink-in flex flex-col gap-6 pt-4 pb-10">
      <header id={`${id}-hero`} className="flex flex-col gap-2">
        <div className="flex items-center gap-2 font-mono text-[10.5px] text-text-faint uppercase tracking-[0.16em]">
          <Briefcase strokeWidth={1.75} className="h-3.5 w-3.5" />
          <span>{data.role}</span>
          <span className="text-text-faint/60">·</span>
          <span className="text-text-muted">Cortex analysis</span>
        </div>
        <h1 className="font-display font-normal text-[22px] text-text-primary leading-tight tracking-[-0.01em]">
          {data.title}
        </h1>
      </header>

      <div
        id={`${id}-takeaway`}
        className="rounded-[14px] border border-[#0F1620]/90 bg-[#0F1620] p-4 text-[#E6ECF4]"
      >
        <div className="mb-1.5 flex items-center gap-2 font-mono text-[10px] text-[#F2B79A] uppercase tracking-[0.16em]">
          <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#F2B79A]" />
          My read
        </div>
        <p className="font-display text-[17px] leading-[1.45] tracking-[-0.005em]">
          {data.takeaway}
        </p>
      </div>

      <section id={`${id}-signals`} className="flex flex-col gap-2.5">
        <SectionLabel>Diagnosis · signals</SectionLabel>
        <div className="flex flex-col gap-3">
          {data.signals.map((signal) => (
            <SignalCard key={signal.id} id={`${id}-signal-${signal.id}`} signal={signal} />
          ))}
        </div>
      </section>

      <section id={`${id}-quotes`} className="flex flex-col gap-2.5">
        <SectionLabel>Exit notes</SectionLabel>
        <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2">
          {data.quotes.map((q, i) => (
            <QuoteCard key={q.cite} id={`${id}-quote-${i}`} quote={q} />
          ))}
        </div>
      </section>

      <section id={`${id}-clusters`} className="flex flex-col gap-2.5">
        <SectionLabel>Rejection reason clusters · auto</SectionLabel>
        <div className="rounded-[14px] border border-border bg-white p-4">
          <ClusterChart id={`${id}-clusters-chart`} bars={data.rejectionClusters} />
        </div>
      </section>

      <section id={`${id}-reengage`} className="flex flex-col gap-2.5">
        <div className="flex items-center justify-between gap-3">
          <SectionLabel>
            Silver medalists · re-engage · top {data.silverMedalists.length}
          </SectionLabel>
          {onDraftAll && (
            <button
              type="button"
              onClick={onDraftAll}
              className="inline-flex items-center gap-1.5 rounded-full border border-text-primary bg-text-primary px-3 py-1.5 font-medium font-sans text-[12px] text-white transition hover:bg-[#222]"
            >
              Draft all {data.silverMedalists.length}
            </button>
          )}
        </div>
        <div className="flex flex-col gap-2.5">
          {data.silverMedalists.map((c) => (
            <SilverCard
              key={c.id}
              id={`${id}-card-${c.id}`}
              candidate={c}
              {...(onDraftNote ? { onDraftNote: () => onDraftNote(c.id) } : {})}
            />
          ))}
        </div>
      </section>
    </div>
  );
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.16em]">
      {children}
    </div>
  );
}

function SignalCard({ id, signal }: { id: string; signal: CortexSignalCard }) {
  return (
    <article
      id={id}
      className="rounded-[14px] border border-border bg-white p-4 transition hover:border-text-primary/20"
    >
      <header className="mb-2 flex items-center gap-2">
        <span
          aria-hidden
          className="h-1.5 w-1.5 rounded-full bg-[#F2B79A] shadow-[0_0_6px_#F2B79A]"
        />
        <h3 className="font-display font-normal text-[18px] text-text-primary leading-tight tracking-[-0.01em]">
          {signal.title}
        </h3>
      </header>
      <p className="text-[13px] text-text-primary leading-[1.55]">{signal.body}</p>
      <div id={`${id}-viz`} className="mt-4">
        {signal.viz.kind === 'panelist_mix' && <PanelistMix viz={signal.viz} />}
        {signal.viz.kind === 'split_bar' && <SplitBar viz={signal.viz} />}
        {signal.viz.kind === 'timeline' && <TimelineViz viz={signal.viz} />}
      </div>
    </article>
  );
}

function PanelistMix({ viz }: { viz: CortexPanelistMixViz }) {
  const executionCount = viz.panelists.filter((p) => p.probe === 'execution').length;
  const strategyCount = viz.panelists.length - executionCount;
  return (
    <div className="flex flex-col gap-2.5">
      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
        {viz.panelists.map((p) => {
          const isExec = p.probe === 'execution';
          return (
            <div
              key={p.label}
              className={cn(
                'flex min-w-0 flex-col gap-1 rounded-[10px] border px-2.5 py-2 text-[10.5px]',
                isExec
                  ? 'border-[#0F1620]/85 bg-[#0F1620] text-[#E6ECF4]'
                  : 'border-[#F2B79A]/60 bg-[#FFF4EE] text-[#7A3A1A]',
              )}
            >
              <span className="truncate font-mono text-[9.5px] uppercase tracking-[0.14em] opacity-75">
                {p.label}
              </span>
              <span className="font-medium leading-tight">
                {isExec ? viz.executionLabel : viz.strategyLabel}
              </span>
            </div>
          );
        })}
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
        <span>
          <span className="text-text-primary">{executionCount}</span> of {viz.panelists.length}{' '}
          execution probe
        </span>
        <span>
          <span className="text-text-primary">{strategyCount}</span> of {viz.panelists.length}{' '}
          leverage probe
        </span>
      </div>
    </div>
  );
}

function SplitBar({ viz }: { viz: CortexSplitBarViz }) {
  return (
    <div className="flex flex-col gap-2">
      <div
        role="img"
        aria-label={`${viz.proLabel} ${viz.proPct}% · ${viz.conLabel} ${viz.conPct}%`}
        className="flex h-3 overflow-hidden rounded-full border border-border"
      >
        <div className="h-full bg-[#5A8C6C]" style={{ width: `${viz.proPct}%` }} />
        <div className="h-full bg-[#C97A4A]" style={{ width: `${viz.conPct}%` }} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 font-mono text-[10px] text-text-muted uppercase tracking-[0.14em]">
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#5A8C6C]" />
          {viz.proLabel} · {viz.proPct}%
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#C97A4A]" />
          {viz.conLabel} · {viz.conPct}%
        </span>
      </div>
    </div>
  );
}

function TimelineViz({ viz }: { viz: CortexTimelineViz }) {
  const days = Math.max(viz.totalDays, 1);
  // Sort so we can alternate caption positions above/below the line — stops
  // labels from stacking on top of each other when events are close in time.
  const sorted = [...viz.events].sort((a, b) => a.day - b.day);
  return (
    <div className="flex flex-col gap-2">
      <div className="relative h-[92px]">
        <div className="absolute top-[44px] right-0 left-0 h-px bg-border" />
        {sorted.map((e, i) => {
          const leftPct = Math.min(100, Math.max(0, (e.day / days) * 100));
          const above = i % 2 === 0;
          const tone =
            e.tone === 'warn'
              ? 'border-[#C97A4A] bg-[#C97A4A] text-white'
              : e.tone === 'accent'
                ? 'border-[#0F1620] bg-[#0F1620] text-[#F2B79A]'
                : 'border-border bg-white text-text-muted';
          return (
            <div
              key={`${e.day}-${e.label}`}
              className="absolute flex -translate-x-1/2 flex-col items-center"
              style={{ left: `${leftPct}%`, top: 0, height: '100%' }}
            >
              {above ? (
                <>
                  <span className="whitespace-nowrap font-mono text-[9.5px] text-text-muted uppercase tracking-[0.12em]">
                    {e.label}
                  </span>
                  <div className="mt-1 h-[14px] w-px bg-border/80" />
                  <div
                    className={cn(
                      'flex h-5 w-5 items-center justify-center rounded-full border font-mono text-[9px]',
                      tone,
                    )}
                  >
                    {e.day}
                  </div>
                </>
              ) : (
                <>
                  <div className="h-[34px]" aria-hidden />
                  <div
                    className={cn(
                      'flex h-5 w-5 items-center justify-center rounded-full border font-mono text-[9px]',
                      tone,
                    )}
                  >
                    {e.day}
                  </div>
                  <div className="mt-1 h-[14px] w-px bg-border/80" />
                  <span className="whitespace-nowrap font-mono text-[9.5px] text-text-muted uppercase tracking-[0.12em]">
                    {e.label}
                  </span>
                </>
              )}
            </div>
          );
        })}
      </div>
      <div className="flex items-center justify-between font-mono text-[9.5px] text-text-faint uppercase tracking-[0.14em]">
        <span>day 0</span>
        <span>day {days}</span>
      </div>
    </div>
  );
}

function QuoteCard({ id, quote }: { id: string; quote: CortexQuoteCard }) {
  return (
    <figure id={id} className="m-0 rounded-[14px] border border-border bg-white p-4">
      <div className="mb-1.5 text-[#F2B79A]">
        <QuoteIcon strokeWidth={1.75} className="h-3.5 w-3.5" />
      </div>
      <blockquote className="m-0 font-display text-[15px] text-text-primary italic leading-[1.4] tracking-[-0.005em]">
        &ldquo;{quote.text}&rdquo;
      </blockquote>
      <figcaption className="mt-2 font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
        {quote.cite}
      </figcaption>
    </figure>
  );
}

function ClusterChart({ id, bars }: { id: string; bars: CortexClusterBar[] }) {
  const max = Math.max(...bars.map((b) => b.pct), 1);
  return (
    <ul id={id} className="flex flex-col gap-2">
      {bars.map((b) => {
        const widthPct = (b.pct / max) * 100;
        const isTop = b.pct === max;
        return (
          <li key={b.label} className="flex flex-col gap-1">
            <div className="flex items-baseline justify-between text-[12px]">
              <span className="text-text-primary">{b.label}</span>
              <span
                className={cn(
                  'font-mono text-[11px] uppercase tracking-[0.1em]',
                  isTop ? 'text-[#D64B1A]' : 'text-text-muted',
                )}
              >
                {b.pct}%
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-surface">
              <div
                className={cn(
                  'h-full rounded-full transition-all',
                  isTop ? 'bg-[#D64B1A]' : 'bg-text-primary/70',
                )}
                style={{ width: `${widthPct}%` }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function SilverCard({
  id,
  candidate,
  onDraftNote,
}: {
  id: string;
  candidate: CortexSilverCandidate;
  onDraftNote?: () => void;
}) {
  return (
    <article id={id} className="rounded-[14px] border border-border bg-white p-4">
      <header className="flex items-start gap-3">
        <div
          aria-hidden
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#0F1620] font-mono text-[11px] text-[#F2B79A] tracking-[0.08em]"
        >
          {candidate.initials}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
            <h3 className="font-display font-normal text-[18px] text-text-primary leading-tight tracking-[-0.01em]">
              {candidate.name}
            </h3>
            <span className="font-mono text-[11px] text-[#D64B1A] uppercase tracking-[0.1em]">
              {candidate.matchPct} match
            </span>
          </div>
          <div className="mt-0.5 font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
            {candidate.tagline}
          </div>
        </div>
      </header>
      <div className="mt-3 grid grid-cols-1 gap-2.5 md:grid-cols-2">
        <div className="rounded-[10px] border border-border/70 bg-surface/60 p-3">
          <div className="mb-1 font-mono text-[9.5px] text-text-faint uppercase tracking-[0.16em]">
            Why passed then
          </div>
          <p className="text-[12.5px] text-text-primary leading-[1.5]">{candidate.whyThen}</p>
        </div>
        <div className="rounded-[10px] border border-[#F2B79A]/50 bg-[#FFF4EE] p-3">
          <div className="mb-1 font-mono text-[9.5px] text-[#7A3A1A] uppercase tracking-[0.16em]">
            Why now
          </div>
          <p className="text-[12.5px] text-text-primary leading-[1.5]">{candidate.whyNow}</p>
        </div>
      </div>
      {onDraftNote && (
        <div className="mt-3 flex">
          <button
            type="button"
            onClick={onDraftNote}
            className="inline-flex items-center gap-1.5 rounded-full border border-border/70 bg-white/70 px-3 py-1.5 font-medium font-sans text-[12px] text-text-primary backdrop-blur-sm transition hover:border-text-primary hover:bg-white/85"
          >
            Draft warm note
          </button>
        </div>
      )}
    </article>
  );
}
