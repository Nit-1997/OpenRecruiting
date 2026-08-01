import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

// Shared visual identity for an agent "thinking trail" — the dark Cortex panel
// (`#0F1620`) whose header row is a glowing `#F2B79A` accent dot + a left label
// and a right-side status slot. Two artifacts render trails (sourcing-strategy:
// collapsible, status-per-step; cortex-insight: streaming active-step) with
// different step models, so the step list stays local to each consumer. This
// primitive owns the duplicated panel chrome (dark rounded card) and the
// dot+label+status header that were previously copy-pasted in each artifact.

const PANEL_BASE =
  'overflow-hidden rounded-[14px] border border-[#0F1620] bg-[#0F1620] text-[#C8D4E3]';

interface ThinkingTrailPanelProps {
  id: string;
  children: ReactNode;
  /** Consumer-specific extras (shadow, padding). */
  className?: string;
}

/** The dark trail panel shell: a rounded `#0F1620` card. */
export function ThinkingTrailPanel({ id, children, className }: ThinkingTrailPanelProps) {
  return (
    <section id={id} className={cn(PANEL_BASE, className)}>
      {children}
    </section>
  );
}

interface ThinkingTrailHeaderProps {
  /** Left-side label, e.g. "Cortex · thinking trail". */
  label: ReactNode;
  /** Right-side status — elapsed label, progress fraction, chevron, etc. The
   * caller styles its own text color so each trail keeps its exact look. */
  status: ReactNode;
  /**
   * Leading accent dot behaviour: `pulse` animates + glows (work in progress),
   * `static` glows without animating, `none` is a flat dot.
   */
  dot?: 'pulse' | 'static' | 'none';
  /** Render as a button (collapsible trails) instead of a static div. */
  onToggle?: () => void;
  /** Spacing/border classes — each consumer keeps its exact layout. */
  className?: string;
}

const HEADER_BASE =
  'flex w-full items-center justify-between font-mono text-[10px] text-[#F2B79A] uppercase tracking-[0.16em]';

/** Header row: glowing accent dot + label on the left, a status slot on the right. */
export function ThinkingTrailHeader({
  label,
  status,
  dot = 'pulse',
  onToggle,
  className,
}: ThinkingTrailHeaderProps) {
  const inner = (
    <>
      <span className="flex items-center gap-2 text-[#F2B79A]">
        <span
          aria-hidden
          className={cn(
            'inline-flex h-2 w-2 rounded-full bg-[#F2B79A]',
            dot === 'pulse' && 'animate-pulse shadow-[0_0_8px_#F2B79A]',
            dot === 'static' && 'shadow-[0_0_8px_#F2B79A]',
          )}
        />
        {label}
      </span>
      <span className="flex items-center gap-2">{status}</span>
    </>
  );

  if (onToggle) {
    return (
      <button type="button" onClick={onToggle} className={cn(HEADER_BASE, className)}>
        {inner}
      </button>
    );
  }
  return <div className={cn(HEADER_BASE, className)}>{inner}</div>;
}
