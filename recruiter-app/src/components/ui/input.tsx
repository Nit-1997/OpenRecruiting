import { cva, type VariantProps } from 'class-variance-authority';
import type { InputHTMLAttributes, ReactNode } from 'react';
import { forwardRef } from 'react';
import { cn } from '@/lib/utils';

const inputVariants = cva(
  [
    'w-full font-sans text-[13px] text-charcoal placeholder:text-text-muted',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/15 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas',
    'disabled:cursor-not-allowed disabled:opacity-60',
  ],
  {
    variants: {
      variant: {
        bordered:
          'h-9 px-3 rounded-input bg-tile border border-border hover:border-border-strong',
        ghost: 'h-9 px-0 bg-transparent border-0 border-b border-transparent focus-visible:border-charcoal rounded-none',
      },
    },
    defaultVariants: {
      variant: 'bordered',
    },
  },
);

export interface InputProps
  extends InputHTMLAttributes<HTMLInputElement>,
    VariantProps<typeof inputVariants> {
  id: string;
  leadingIcon?: ReactNode;
  trailingAction?: ReactNode;
  mono?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  (
    {
      id,
      className,
      variant,
      leadingIcon,
      trailingAction,
      mono,
      ...props
    },
    ref,
  ) => {
    const baseClass = cn(
      inputVariants({ variant }),
      mono && 'font-mono',
      leadingIcon && 'pl-9',
      trailingAction && 'pr-9',
      className,
    );

    if (!leadingIcon && !trailingAction) {
      return <input id={id} ref={ref} className={baseClass} {...props} />;
    }

    return (
      <div className="relative inline-flex w-full items-center">
        {leadingIcon && (
          <span className="pointer-events-none absolute left-3 flex items-center text-text-muted [&_svg]:size-4">
            {leadingIcon}
          </span>
        )}
        <input id={id} ref={ref} className={baseClass} {...props} />
        {trailingAction && (
          <span className="absolute right-2 flex items-center">{trailingAction}</span>
        )}
      </div>
    );
  },
);
Input.displayName = 'Input';
