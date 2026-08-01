import { cva, type VariantProps } from 'class-variance-authority';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { forwardRef } from 'react';
import { cn } from '@/lib/utils';

const iconButtonVariants = cva(
  [
    'inline-flex items-center justify-center rounded-full transition-colors cursor-pointer',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/15 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas',
    'disabled:pointer-events-none disabled:opacity-50',
  ],
  {
    variants: {
      variant: {
        primary: 'bg-charcoal text-white hover:bg-charcoal/90',
        secondary:
          'border border-border-strong bg-tile text-charcoal hover:bg-surface',
        ghost: 'bg-transparent text-text-secondary hover:bg-surface hover:text-charcoal',
        destructive: 'bg-red-600 text-white hover:bg-red-700',
      },
      size: {
        sm: 'size-7 [&_svg]:size-3.5',
        md: 'size-8 [&_svg]:size-4',
        lg: 'size-10 [&_svg]:size-5',
      },
    },
    defaultVariants: {
      variant: 'ghost',
      size: 'md',
    },
  },
);

export interface IconButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof iconButtonVariants> {
  id: string;
  children: ReactNode;
  'aria-label': string;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ id, className, variant, size, children, ...props }, ref) => (
    <button
      id={id}
      ref={ref}
      type="button"
      className={cn(iconButtonVariants({ variant, size }), className)}
      {...props}
    >
      {children}
    </button>
  ),
);
IconButton.displayName = 'IconButton';
