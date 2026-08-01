import type { JSX } from 'react';
import type { RoundCategory } from '@/types/intake';

const LABELS: Record<RoundCategory, string> = {
  screening: 'Screening',
  coding: 'Coding',
  design: 'Design',
  behavioral: 'Behavioral',
  domain: 'Domain',
  culture: 'Culture',
  panel: 'Panel',
  assessment: 'Assessment',
};

const STYLES: Record<RoundCategory, string> = {
  screening: 'bg-slate-800 text-slate-200 border-slate-700',
  coding: 'bg-cortex-900/40 text-cortex-300 border-cortex-700',
  design: 'bg-amber-900/40 text-amber-300 border-amber-700',
  behavioral: 'bg-violet-900/40 text-violet-300 border-violet-700',
  domain: 'bg-emerald-900/40 text-emerald-300 border-emerald-700',
  culture: 'bg-rose-900/40 text-rose-300 border-rose-700',
  panel: 'bg-sky-900/40 text-sky-300 border-sky-700',
  assessment: 'bg-fuchsia-900/40 text-fuchsia-300 border-fuchsia-700',
};

interface Props {
  category: RoundCategory;
  id?: string;
}

export function RoundCategoryBadge({ category, id }: Props): JSX.Element {
  return (
    <span
      id={id}
      data-category={category}
      className={`inline-flex items-center px-2 py-0.5 rounded border text-xs font-dm-mono uppercase tracking-wider ${STYLES[category]}`}
    >
      {LABELS[category]}
    </span>
  );
}
