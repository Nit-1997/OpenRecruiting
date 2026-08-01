import type { HTMLAttributes, ReactNode } from 'react';
import { forwardRef } from 'react';
import { cn } from '@/lib/utils';

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  id: string;
  children: ReactNode;
  hoverable?: boolean;
  interactive?: boolean;
}

export const Card = forwardRef<HTMLDivElement, CardProps>(
  ({ id, className, children, hoverable, interactive, ...props }, ref) => (
    <div
      id={id}
      ref={ref}
      tabIndex={interactive ? 0 : undefined}
      role={interactive ? 'button' : undefined}
      className={cn(
        'bg-tile border border-border rounded-card-lg shadow-card p-4 transition-colors',
        hoverable && 'hover:border-border-strong',
        interactive &&
          'cursor-pointer hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black/15 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas',
        className,
      )}
      {...props}
    >
      <div className="contents">{children}</div>
    </div>
  ),
);
Card.displayName = 'Card';
