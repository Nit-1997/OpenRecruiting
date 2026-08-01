'use client';

import { BrandIcon } from '@/components/icons/brand-icons';
import { useShellSync } from '@/hooks/use-shell-sync';

interface StubCanvasProps {
  id: string;
  title: string;
  sub: string;
  phase: string;
}

export function StubCanvas({ id, title, sub, phase }: StubCanvasProps) {
  useShellSync();
  return (
    <div id={id}>
      <div id={`${id}-head`} className="flex items-center justify-between gap-3 pt-6 pb-3">
        <div
          id={`${id}-eyebrow`}
          className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]"
        >
          {title} · stub ({phase})
        </div>
      </div>

      <div id={`${id}-msg`} className="flex max-w-[700px] gap-3.5 py-3">
        <div
          id={`${id}-avatar`}
          aria-hidden
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white"
        >
          <BrandIcon className="h-6 w-6 text-text-primary" />
        </div>
        <div>
          <p
            id={`${id}-prose`}
            className="mb-3 font-display font-normal text-[26px] leading-[1.35] tracking-[-0.005em]"
          >
            {sub}
          </p>
        </div>
      </div>
    </div>
  );
}
