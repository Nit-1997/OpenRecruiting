'use client';

import { ChevronRight, Clock } from 'lucide-react';
import { BrandIcon } from '@/components/icons/brand-icons';
import type { Round } from '@/types';
import { RoundCategoryBadge } from './round-category-badge';

export interface RoundCardProps {
  id: string;
  round: Round;
  onSelect: (roundId: string) => void;
  isBuilding?: boolean;
}

function pluralize(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? '' : 's'}`;
}

export function RoundCard({ id, round, onSelect, isBuilding = false }: RoundCardProps) {
  const rowId = `${id}-row-${round.id}`;
  const hasDetails = round.feedbackQuestions.length > 0 || round.guidelines.length > 0;
  const aiHosted = round.screeningAgentEnabled === true;
  // Eligibility nudge: backend says OpenRecruiting can host this round, but it isn't
  // attached yet. Suppressed once attached (the "takes this round" badge wins).
  const aiEligible = round.aiScreenable === true && !aiHosted;

  return (
    <button
      id={rowId}
      type="button"
      onClick={() => onSelect(round.id)}
      className={`group relative flex w-full items-stretch gap-3.5 overflow-hidden rounded-[14px] border bg-white p-4 text-left shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition hover:border-cortex-500/40 hover:shadow-[0_2px_8px_rgba(0,0,0,0.04)] ${
        aiHosted
          ? 'border-cortex-500/40 bg-gradient-to-br from-cortex-500/10 to-cortex-50'
          : 'border-border'
      }`}
    >
      <span
        id={`${rowId}-number`}
        aria-hidden
        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full border font-medium font-mono text-[12px] ${
          aiHosted
            ? 'border-cortex-500/30 bg-cortex-500/10 text-cortex-500'
            : 'border-border bg-surface text-text-primary'
        }`}
      >
        {round.roundNumber}
      </span>

      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex min-w-0 items-start gap-2">
          <span
            id={`${rowId}-name`}
            className="truncate font-medium font-sans text-[14.5px] text-text-primary leading-tight tracking-[-0.005em]"
          >
            {round.name}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <RoundCategoryBadge id={`${rowId}-badge`} category={round.category} />
          <span
            id={`${rowId}-duration`}
            className="inline-flex items-center gap-1 rounded-full border border-border bg-surface px-2 py-0.5 font-mono text-[10px] text-text-muted uppercase tracking-[0.14em]"
          >
            <Clock strokeWidth={1.75} className="h-2.5 w-2.5" />
            {round.durationMinutes} min
          </span>
          {hasDetails && (
            <span
              id={`${rowId}-summary`}
              className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]"
            >
              {pluralize(round.feedbackQuestions.length, 'question')} ·{' '}
              {pluralize(round.guidelines.length, 'guideline')}
            </span>
          )}
          {aiHosted && (
            <span
              id={`${rowId}-ai-badge`}
              className="inline-flex items-center gap-1 rounded-full border border-cortex-500/30 bg-white px-2 py-0.5 font-medium font-mono text-[10px] text-cortex-500 uppercase tracking-[0.14em]"
            >
              <BrandIcon className="h-2.5 w-2.5" />
              OpenRecruiting takes this round
              {round.screeningAgentQuestions ? ` · ${round.screeningAgentQuestions.length}Q` : ''}
            </span>
          )}
          {aiEligible && (
            <span
              id={`${rowId}-ai-nudge`}
              title={
                round.aiScreenableReason ?? 'OpenRecruiting can host this round as a screening call.'
              }
              className="inline-flex items-center gap-1 rounded-full border border-cortex-500/30 border-dashed bg-cortex-500/5 px-2 py-0.5 font-medium font-mono text-[10px] text-cortex-500 uppercase tracking-[0.14em]"
            >
              <BrandIcon className="h-2.5 w-2.5" />
              OpenRecruiting can take this round
            </span>
          )}
        </div>
      </div>

      <ChevronRight
        aria-hidden
        strokeWidth={1.75}
        className="h-4 w-4 shrink-0 self-center text-text-muted transition group-hover:translate-x-0.5 group-hover:text-text-primary"
      />

      {isBuilding && <span id={`${rowId}-shimmer`} aria-hidden className="mz-shimmer-overlay" />}
    </button>
  );
}
