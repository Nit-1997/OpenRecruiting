'use client';

import { Check, Cpu } from 'lucide-react';
import { BrandIcon } from '@/components/icons/brand-icons';
import type { CortexStatCard, CortexTrailStep } from '@/fixtures/cortex-insights';
import { cn } from '@/lib/utils';
import { useArtifactStore } from '@/stores';

interface CortexTrailArtifactData {
  title: string;
  elapsedLabel: string;
  steps: CortexTrailStep[];
  activeStepNum: string | null;
  stats: CortexStatCard[];
  complete: boolean;
}

interface CortexTrailMsgProps {
  id: string;
  artifactId: string;
  time?: string;
}

export function CortexTrailMsg({ id, artifactId, time }: CortexTrailMsgProps) {
  const artifact = useArtifactStore((s) => s.artifacts[artifactId]);
  if (!artifact) return null;
  const data = artifact.data as CortexTrailArtifactData;
  if (!data?.steps) return null;

  const activeIdx = data.activeStepNum
    ? data.steps.findIndex((s) => s.num === data.activeStepNum)
    : -1;
  const maxIdx = data.complete ? data.steps.length - 1 : activeIdx >= 0 ? activeIdx : -1;
  const visible = maxIdx >= 0 ? data.steps.slice(0, maxIdx + 1) : [];

  return (
    <div id={id} className="flex max-w-[760px] items-start gap-3.5 py-2">
      <div
        id={`${id}-avatar`}
        aria-hidden
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white"
      >
        <BrandIcon className="h-6 w-6 text-text-primary" />
      </div>
      <div id={`${id}-body`} className="min-w-0 flex-1">
        <div
          id={`${id}-meta`}
          className="mb-1.5 flex items-center gap-2 font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]"
        >
          <span className="text-text-muted">openrecruiting cortex · thinking trail</span>
          {time && <span>{time}</span>}
        </div>

        <section
          id={`${id}-trail`}
          className="max-w-[620px] overflow-hidden rounded-[14px] border border-[#0F1620] bg-[#0F1620] p-4 text-[#C8D4E3] shadow-[0_6px_18px_rgba(15,22,32,0.25)]"
        >
          <div className="mb-3 flex items-center justify-between border-[rgba(200,212,227,0.25)] border-b border-dashed pb-2 font-mono text-[10px] uppercase tracking-[0.16em]">
            <span className="flex items-center gap-2 text-[#F2B79A]">
              <Cpu strokeWidth={1.75} className="h-3 w-3" />
              cortex · agent trail
            </span>
            <span className="text-[rgba(200,212,227,0.5)]">elapsed · {data.elapsedLabel}</span>
          </div>
          <ol className="flex flex-col gap-1 font-mono text-[11.5px] leading-[1.55]">
            {visible.map((s) => {
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
            })}
            {data.complete && (
              <li
                id={`${id}-step-complete`}
                className="mt-1 inline-flex items-center gap-1.5 font-mono text-[10.5px] text-[#8DD18D] uppercase tracking-[0.14em]"
              >
                <Check strokeWidth={2} className="h-3 w-3" />
                Analysis ready · opened on the right
              </li>
            )}
          </ol>
        </section>

        {data.stats.length > 0 && (
          <div
            id={`${id}-stats`}
            className="mt-3 grid max-w-[620px] grid-cols-1 gap-2.5 md:grid-cols-2"
          >
            {data.stats.map((card) => (
              <section
                key={card.title}
                className="rounded-[14px] border border-border bg-white p-3.5"
              >
                <div className="mb-2 flex items-center justify-between border-border border-b pb-1.5">
                  <span className="font-medium text-[12.5px]">{card.title}</span>
                  <span className="font-mono text-[9.5px] text-text-muted uppercase tracking-[0.14em]">
                    auto
                  </span>
                </div>
                <ul className="flex flex-col gap-1">
                  {card.rows.map((row) => (
                    <li
                      key={row.label}
                      className="flex items-center justify-between py-0.5 text-[12px] text-text-primary"
                    >
                      <span>{row.label}</span>
                      <span className="font-mono text-[10.5px] text-[#D64B1A] uppercase tracking-[0.1em]">
                        {row.value}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
