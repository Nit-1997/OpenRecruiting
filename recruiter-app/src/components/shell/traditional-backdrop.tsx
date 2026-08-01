'use client';

import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { useShellStore } from '@/stores';

interface TraditionalBackdropProps {
  id: string;
  children: ReactNode;
}

export function TraditionalBackdrop({ id, children }: TraditionalBackdropProps) {
  const mode = useShellStore((s) => s.mode());
  const dimmed = mode === 'qna';
  return (
    <div
      id={id}
      aria-hidden={dimmed}
      className={cn(
        'h-full transition-opacity',
        dimmed ? 'pointer-events-none opacity-40' : 'opacity-100',
      )}
    >
      {children}
    </div>
  );
}
