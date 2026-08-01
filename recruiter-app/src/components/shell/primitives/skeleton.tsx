'use client';

import { cn } from '@/lib/utils';

interface SkeletonProps {
  id: string;
  className?: string;
  rounded?: 'sm' | 'md' | 'lg' | 'pill';
}

const ROUNDED_MAP = {
  sm: 'rounded-[6px]',
  md: 'rounded-[10px]',
  lg: 'rounded-[14px]',
  pill: 'rounded-full',
} as const;

export function Skeleton({ id, className, rounded = 'md' }: SkeletonProps) {
  return <div id={id} aria-hidden className={cn('mz-skeleton', ROUNDED_MAP[rounded], className)} />;
}

interface SkeletonLinesProps {
  id: string;
  lines?: number;
  widths?: string[];
  className?: string;
}

export function SkeletonLines({
  id,
  lines = 3,
  widths = ['100%', '94%', '78%'],
  className,
}: SkeletonLinesProps) {
  return (
    <div id={id} className={cn('flex flex-col gap-2', className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          // biome-ignore lint/suspicious/noArrayIndexKey: static placeholder list
          key={i}
          id={`${id}-line-${i}`}
          aria-hidden
          className="mz-skeleton h-3 rounded-[4px]"
          style={{ width: widths[i % widths.length] }}
        />
      ))}
    </div>
  );
}
