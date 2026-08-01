import { cva, type VariantProps } from 'class-variance-authority';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { forwardRef } from 'react';
import { cn } from '@/lib/utils';

const buttonVariants = cva(
  [
    'inline-flex items-center justify-center gap-2',
    'font-sans font-medium whitespace-nowrap',
    'rounded-full transition-colors cursor-pointer',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/15 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas',
    'disabled:pointer-events-none disabled:opacity-50',
  ],
  {
    variants: {
      variant: {
        // text-canvas (not text-white): --canvas flips OPPOSITE to --charcoal
        // in dark mode (charcoal -> light), so the foreground stays readable on
        // the charcoal fill in BOTH light and dark themes.
        primary: 'bg-charcoal text-canvas hover:bg-charcoal/90',
        secondary:
          'border border-border-strong bg-tile text-charcoal hover:bg-surface',
        ghost: 'bg-transparent text-text-secondary hover:bg-surface hover:text-charcoal',
        destructive: 'bg-red-600 text-white hover:bg-red-700',
      },
      size: {
        sm: 'h-7 px-3 text-xs',
        md: 'h-9 px-4 text-[13px]',
        lg: 'h-11 px-6 text-[15px]',
      },
    },
    defaultVariants: {
      variant: 'primary',
      size: 'md',
    },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  id: string;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ id, className, variant, size, icon, children, ...props }, ref) => {
    return (
      <button
        id={id}
        ref={ref}
        type="button"
        className={cn(buttonVariants({ variant, size }), className)}
        {...props}
      >
        {icon}
        {children}
      </button>
    );
  },
);
Button.displayName = 'Button';
