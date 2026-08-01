import { cn } from '@/lib/utils';

interface AtsSourceBadgeProps {
  id: string;
  source?: string | null | undefined;
  provider?: string | null | undefined;
  className?: string;
}

/**
 * Provider pill for ATS-imported requisitions ("Workable", "Ashby", generic
 * "ATS" fallback). Renders nothing for native rows so it can be placed
 * unconditionally next to any requisition title.
 */
export function AtsSourceBadge({ id, source, provider, className }: AtsSourceBadgeProps) {
  if (source !== 'ats_sync') return null;
  const label = provider ? provider.charAt(0).toUpperCase() + provider.slice(1) : 'ATS';
  return (
    <span
      id={id}
      className={cn(
        'inline-flex shrink-0 items-center rounded-full border border-border bg-surface px-2 py-0.5 font-mono text-[9.5px] text-text-muted uppercase tracking-[0.14em]',
        className,
      )}
    >
      {label}
    </span>
  );
}
