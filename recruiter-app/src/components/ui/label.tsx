import type { LabelHTMLAttributes, ReactNode } from 'react';
import { forwardRef } from 'react';
import { cn } from '@/lib/utils';

type LabelVariant = 'default' | 'accent';

export interface LabelProps extends LabelHTMLAttributes<HTMLLabelElement> {
  id: string;
  children: ReactNode;
  variant?: LabelVariant;
  dot?: string;
}

export const Label = forwardRef<HTMLLabelElement, LabelProps>(
  ({ id, className, children, variant = 'default', dot, ...props }, ref) => {
    if (dot) {
      return (
        <span id={`${id}-wrap`} className="inline-flex items-center gap-1.5">
          <span
            data-label-dot
            className="size-1.5 rounded-full"
            style={{ backgroundColor: dot }}
          />
          <label
            id={id}
            ref={ref}
            className={cn('font-mono-label text-text-muted', className)}
            {...props}
          >
            {children}
          </label>
        </span>
      );
    }
    if (variant === 'accent') {
      return (
        <label
          id={id}
          ref={ref}
          className={cn(
            'inline-flex items-center rounded-full bg-surface px-2.5 py-0.5 font-mono-label text-charcoal',
            className,
          )}
          {...props}
        >
          {children}
        </label>
      );
    }
    return (
      <label
        id={id}
        ref={ref}
        className={cn('font-mono-label text-text-muted', className)}
        {...props}
      >
        {children}
      </label>
    );
  },
);
Label.displayName = 'Label';
