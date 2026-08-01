import type { RoundCategory } from '@/types';

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

const TINT: Record<RoundCategory, string> = {
  screening: 'border-[#BFDBFE] bg-[#EFF6FF] text-[#1D4ED8]',
  coding: 'border-[#DDD6FE] bg-[#F5F3FF] text-[#6D28D9]',
  design: 'border-[#FBCFE8] bg-[#FDF2F8] text-[#9D174D]',
  behavioral: 'border-[#FDE68A] bg-[#FFFBEB] text-[#B45309]',
  domain: 'border-[#C7D2FE] bg-[#EEF2FF] text-[#4338CA]',
  culture: 'border-[#A7F3D0] bg-[#ECFDF5] text-[#047857]',
  panel: 'border-[#FBCFE8] bg-[#FDF2F8] text-[#9D174D]',
  assessment: 'border-[#FED7AA] bg-[#FFF7ED] text-[#C2410C]',
};

export interface RoundCategoryBadgeProps {
  id: string;
  category: RoundCategory;
}

export function RoundCategoryBadge({ id, category }: RoundCategoryBadgeProps) {
  return (
    <span
      id={id}
      data-category={category}
      className={`inline-flex items-center rounded-full border px-2 py-0.5 font-medium font-mono text-[10px] uppercase tracking-[0.14em] ${TINT[category]}`}
    >
      {LABELS[category]}
    </span>
  );
}
