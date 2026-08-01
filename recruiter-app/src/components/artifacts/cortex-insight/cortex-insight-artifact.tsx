'use client';

import { Check, Cpu } from 'lucide-react';
import { cn } from '@/lib/utils';
import { ThinkingTrailHeader, ThinkingTrailPanel } from '../_shared/thinking-trail';
import { useTypedArtifact } from '../_shared/use-artifact-data';

export interface CortexInsightArtifactProps {
  id: string;
  artifactId: string;
}

export function CortexInsightArtifact({ id, artifactId }: CortexInsightArtifactProps) {
  const artifact = useTypedArtifact(artifactId, 'cortex-insight');
  if (!artifact) return null;
  const data = artifact.data;
  if (!data?.steps) {
    return (
      <div id={id} className="animate-pulse pt-2 text-[12.5px] text-text-muted">
        Cortex is thinking…
      </div>
    );
  }

  return (
    <div id={id} className="flex flex-col gap-5 pb-10">
      <header className="flex items-start gap-3">
        <div
          aria-hidden
          className="flex h-10 w-10 items-center justify-center rounded-[12px] bg-[#0F1620] text-[#F2B79A]"
        >
          <Cpu strokeWidth={1.75} className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="font-display font-normal text-[22px] text-text-primary leading-tight tracking-[-0.01em]">
            {data.title}
          </h2>
          <p className="mt-1 text-[12.5px] text-text-muted">
            Cortex thinking trail — streaming as evidence is joined.
          </p>
        </div>
      </header>

      <ThinkingTrailPanel
        id={`${id}-trail`}
        className="p-4 shadow-[0_6px_18px_rgba(15,22,32,0.25)]"
      >
        <ThinkingTrailHeader
          label="Cortex · thinking trail"
          dot="static"
          className="mb-3 border-[rgba(200,212,227,0.25)] border-b border-dashed pb-2"
          status={
            <span className="text-[rgba(200,212,227,0.5)]">elapsed · {data.elapsedLabel}</span>
          }
        />
        <ol className="flex flex-col gap-1 font-mono text-[11.5px] leading-[1.55]">
          {(() => {
            const activeIdx = data.activeStepNum
              ? data.steps.findIndex((s) => s.num === data.activeStepNum)
              : -1;
            const maxIdx = data.complete ? data.steps.length - 1 : activeIdx >= 0 ? activeIdx : -1;
            const visible = maxIdx >= 0 ? data.steps.slice(0, maxIdx + 1) : [];
            return visible.map((s) => {
              const active = data.activeStepNum === s.num && !data.complete;
              return (
                <li
                  key={s.num}
                  id={`${id}-step-${s.num}`}
                  className={cn(
                    'grid grid-cols-[22px_1fr] gap-2 border-[rgba(200,212,227,0.12)] border-b border-dotted py-1 last:border-b-0',
                    'motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-200',
                    active && 'text-[#F2B79A]',
                  )}
                >
                  <span
                    className={cn(
                      'pt-[2px] text-[9.5px]',
                      active ? 'text-[#F2B79A]' : 'text-[rgba(200,212,227,0.4)]',
                    )}
                  >
                    {s.num}
                    {active ? ' ▸' : ''}
                  </span>
                  <span>{s.body}</span>
                </li>
              );
            });
          })()}
          {data.complete && (
            <li
              id={`${id}-step-complete`}
              className="mt-1 inline-flex items-center gap-1.5 font-mono text-[10.5px] text-[#8DD18D] uppercase tracking-[0.14em]"
            >
              <Check strokeWidth={2} className="h-3 w-3" />
              Response ready
            </li>
          )}
        </ol>
      </ThinkingTrailPanel>

      {data.stats.map((card) => (
        <section
          key={card.title}
          id={`${id}-stat-${card.title}`}
          className="rounded-[14px] border border-border bg-white p-4"
        >
          <div className="mb-2 flex items-center justify-between border-border border-b pb-1.5">
            <span className="font-medium text-[13px]">{card.title}</span>
            <span className="font-mono text-[9.5px] text-text-muted uppercase tracking-[0.14em]">
              auto
            </span>
          </div>
          <ul className="flex flex-col gap-1">
            {card.rows.map((row) => (
              <li
                key={row.label}
                className="flex items-center justify-between py-0.5 text-[12.5px] text-text-primary"
              >
                <span>{row.label}</span>
                <span className="font-mono text-[11px] text-[#D64B1A] uppercase tracking-[0.1em]">
                  {row.value}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
