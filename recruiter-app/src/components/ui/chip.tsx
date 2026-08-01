import { Check } from 'lucide-react';
import type { HTMLAttributes, ReactNode } from 'react';
import { forwardRef } from 'react';
import { cn } from '@/lib/utils';

type ChipVariant = 'status' | 'action' | 'assumption';

export interface ChipProps extends HTMLAttributes<HTMLElement> {
  id: string;
  variant: ChipVariant;
  children: ReactNode;
  dotColor?: string;
  onClick?: () => void;
}

export const Chip = forwardRef<HTMLElement, ChipProps>(
  ({ id, variant, children, dotColor, onClick, className, ...rest }, ref) => {
    const base =
      'inline-flex items-center gap-1.5 rounded-full font-sans text-[11px] font-medium px-2.5 py-1 transition-colors';

    if (variant === 'action') {
      return (
        <button
          id={id}
          ref={ref as React.Ref<HTMLButtonElement>}
          type="button"
          onClick={onClick}
          className={cn(
            base,
            'border border-border-strong bg-tile text-charcoal cursor-pointer hover:bg-surface',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/15 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas',
            className,
          )}
          {...(rest as HTMLAttributes<HTMLButtonElement>)}
        >
          {children}
        </button>
      );
    }

    if (variant === 'assumption') {
      return (
        <span
          id={id}
          ref={ref as React.Ref<HTMLSpanElement>}
          className={cn(
            base,
            'bg-emerald-50 border border-emerald-200 text-emerald-800',
            className,
          )}
          {...(rest as HTMLAttributes<HTMLSpanElement>)}
        >
          <Check data-chip-check className="size-3" strokeWidth={2} />
          {children}
        </span>
      );
    }

    return (
      <span
        id={id}
        ref={ref as React.Ref<HTMLSpanElement>}
        className={cn(
          base,
          'border border-border bg-surface text-text-secondary',
          className,
        )}
        {...(rest as HTMLAttributes<HTMLSpanElement>)}
      >
        {dotColor && (
          <span
            data-chip-dot
            className="size-1.5 rounded-full"
            style={{ backgroundColor: dotColor }}
          />
        )}
        {children}
      </span>
    );
  },
);
Chip.displayName = 'Chip';
