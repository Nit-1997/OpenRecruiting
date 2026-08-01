'use client';

import { Check, ChevronDown, MinusCircle, Quote, XCircle } from 'lucide-react';
import { useState } from 'react';
import type {
  DetailedEvidenceBundle,
  DetailedEvidenceVerdict,
  DetailedScorecard,
  DetailedScorecardCriterion,
} from '@/fixtures/detailed-scorecards';
import { cn } from '@/lib/utils';

const VERDICT_STYLE: Record<
  DetailedEvidenceVerdict,
  { label: string; chip: string; dot: string; icon: React.ReactNode }
> = {
  supported: {
    label: 'Supported',
    chip: 'border-[#A7F3D0] bg-[#ECFDF5] text-[#047857]',
    dot: 'bg-[#047857]',
    icon: <Check strokeWidth={1.75} className="h-3 w-3" />,
  },
  contradicted: {
    label: 'Contradicted',
    chip: 'border-[#FECACA] bg-[#FEF2F2] text-[#B91C1C]',
    dot: 'bg-[#B91C1C]',
    icon: <XCircle strokeWidth={1.75} className="h-3 w-3" />,
  },
  not_supported: {
    label: 'Not Supported',
    chip: 'border-border bg-surface text-text-muted',
    dot: 'bg-text-faint',
    icon: <MinusCircle strokeWidth={1.75} className="h-3 w-3" />,
  },
};

const ROUND_VERDICT_STYLE: Record<DetailedScorecard['verdict'], { label: string; chip: string }> = {
  strong_yes: {
    label: 'Strong yes',
    chip: 'border-[#A7F3D0] bg-[#ECFDF5] text-[#047857]',
  },
  yes: { label: 'Yes', chip: 'border-[#BFDBFE] bg-[#EFF6FF] text-[#1E40AF]' },
  maybe: { label: 'Maybe', chip: 'border-[#FDE68A] bg-[#FFFBEB] text-[#B45309]' },
  no: { label: 'No', chip: 'border-[#FECACA] bg-[#FEF2F2] text-[#B91C1C]' },
  strong_no: { label: 'Strong no', chip: 'border-[#FECACA] bg-[#FEE2E2] text-[#991B1B]' },
};

export function DetailedScorecardSection({
  id,
  scorecard,
}: {
  id: string;
  scorecard: DetailedScorecard;
}) {
  const verdictStyle = ROUND_VERDICT_STYLE[scorecard.verdict];
  return (
    <section
      id={id}
      aria-label="Detailed scorecard"
      className="rounded-[16px] border border-border bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)]"
    >
      <header id={`${id}-head`} className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]">
            {scorecard.roundLabel} · Scorecard
          </div>
          <h3
            id={`${id}-title`}
            className="mt-1 font-display text-[22px] text-text-primary leading-tight tracking-[-0.005em]"
          >
            Round verdict
          </h3>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <span
            id={`${id}-verdict`}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-medium font-sans text-[12px]',
              verdictStyle.chip,
            )}
          >
            <Check strokeWidth={1.75} className="h-3 w-3" />
            {verdictStyle.label}
          </span>
          <span
            id={`${id}-date`}
            className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]"
          >
            {scorecard.verdictDate}
          </span>
        </div>
      </header>

      <div
        id={`${id}-summary`}
        className="mb-5 rounded-[12px] border border-border/70 bg-surface/40 px-4 py-3"
      >
        <div className="mb-1.5 font-mono text-[10px] text-text-faint uppercase tracking-[0.18em]">
          Round summary
        </div>
        <p className="text-[13px] text-text-secondary leading-[1.6]">{scorecard.summary}</p>
      </div>

      <div id={`${id}-criteria`} className="flex flex-col gap-3">
        <div className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]">
          Evaluation criteria
        </div>
        <ol id={`${id}-criteria-list`} className="flex flex-col gap-4">
          {scorecard.criteria.map((criterion, idx) => (
            <CriterionCard
              key={criterion.id}
              id={`${id}-criterion-${criterion.id}`}
              criterion={criterion}
              index={idx + 1}
            />
          ))}
        </ol>
      </div>
    </section>
  );
}

function CriterionCard({
  id,
  criterion,
  index,
}: {
  id: string;
  criterion: DetailedScorecardCriterion;
  index: number;
}) {
  const counts = summarizeVerdicts(criterion.bundles);
  return (
    <li
      id={id}
      className="rounded-[14px] border border-border bg-white p-4 shadow-[0_1px_2px_rgba(0,0,0,0.02)]"
    >
      <header id={`${id}-head`} className="mb-2">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h4
              id={`${id}-title`}
              className="font-display text-[17px] text-text-primary leading-tight tracking-[-0.005em]"
            >
              {index}. {criterion.title}
            </h4>
            <p id={`${id}-desc`} className="mt-1 text-[12.5px] text-text-muted leading-[1.5]">
              {criterion.description}
            </p>
          </div>
          <VerdictCountPills counts={counts} />
        </div>
      </header>
      <p id={`${id}-body`} className="mb-3 text-[13px] text-text-secondary leading-[1.6]">
        {criterion.body}
      </p>
      <ul id={`${id}-bundles`} className="flex flex-col gap-2.5">
        {criterion.bundles.map((bundle, bi) => (
          <BundleCard
            // biome-ignore lint/suspicious/noArrayIndexKey: evidence bundles are authored in a stable order per criterion
            key={bi}
            id={`${id}-bundle-${bi}`}
            bundle={bundle}
          />
        ))}
      </ul>
    </li>
  );
}

function BundleCard({ id, bundle }: { id: string; bundle: DetailedEvidenceBundle }) {
  const style = VERDICT_STYLE[bundle.verdict];
  const [open, setOpen] = useState(false);
  const quotesId = `${id}-quotes`;
  return (
    <li id={id} className="rounded-[12px] border border-border bg-surface/30">
      <button
        id={`${id}-toggle`}
        type="button"
        aria-expanded={open}
        aria-controls={quotesId}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full flex-wrap items-start justify-between gap-2 rounded-[12px] p-3.5 text-left transition-colors hover:bg-surface/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-text-primary/30"
      >
        <p
          id={`${id}-heading`}
          className="min-w-0 flex-1 font-medium text-[13px] text-text-primary leading-[1.45]"
        >
          {bundle.heading}
        </p>
        <span className="flex shrink-0 items-center gap-2">
          <span
            id={`${id}-verdict`}
            className={cn(
              'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.14em]',
              style.chip,
            )}
          >
            {style.icon}
            {style.label}
          </span>
          <span
            aria-hidden
            className="flex h-5 w-5 items-center justify-center rounded-full text-text-muted"
          >
            <ChevronDown
              strokeWidth={1.75}
              className={cn('h-3.5 w-3.5 transition-transform', open && 'rotate-180')}
            />
          </span>
        </span>
      </button>
      {open && (
        <ul id={quotesId} className="flex flex-col gap-2 px-3.5 pt-1 pb-3.5">
          {bundle.quotes.map((quote, qi) => (
            <li
              // biome-ignore lint/suspicious/noArrayIndexKey: quote list is a stable authored list per bundle
              key={qi}
              id={`${id}-quote-${qi}`}
              className="flex items-start gap-2"
            >
              <span
                aria-hidden
                className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-white text-text-muted"
              >
                <Quote strokeWidth={1.75} className="h-2.5 w-2.5" />
              </span>
              <p className="min-w-0 flex-1 text-[12.5px] text-text-secondary italic leading-[1.5]">
                {quote}
              </p>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function VerdictCountPills({ counts }: { counts: Record<DetailedEvidenceVerdict, number> }) {
  const entries = (['supported', 'contradicted', 'not_supported'] as const).filter(
    (k) => counts[k] > 0,
  );
  if (entries.length === 0) return null;
  return (
    <div className="flex shrink-0 items-center gap-1.5">
      {entries.map((k) => {
        const style = VERDICT_STYLE[k];
        return (
          <span
            key={k}
            className={cn(
              'inline-flex min-w-[1.5rem] items-center justify-center rounded-full border px-2 py-0.5 font-medium font-mono text-[11px]',
              style.chip,
            )}
            title={style.label}
          >
            {counts[k]}
          </span>
        );
      })}
    </div>
  );
}

function summarizeVerdicts(
  bundles: DetailedEvidenceBundle[],
): Record<DetailedEvidenceVerdict, number> {
  return bundles.reduce<Record<DetailedEvidenceVerdict, number>>(
    (acc, b) => {
      acc[b.verdict] += 1;
      return acc;
    },
    { supported: 0, contradicted: 0, not_supported: 0 },
  );
}
