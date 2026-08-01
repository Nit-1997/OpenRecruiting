'use client';

import { useShellSync } from '@/hooks/use-shell-sync';
import type { RailViewId } from '@/types';
import { RAIL_VIEW_LABELS } from '@/types';

interface StubViewProps {
  id: string;
  viewId: RailViewId;
  sub: string;
  phase: string;
}

export function StubView({ id, viewId, sub, phase }: StubViewProps) {
  useShellSync();
  return (
    <div id={id} className="pt-11">
      <h1
        id={`${id}-title`}
        className="mb-3 font-display font-normal text-[28px] leading-[1.1] tracking-[-0.01em]"
      >
        {RAIL_VIEW_LABELS[viewId]}
      </h1>
      <p id={`${id}-sub`} className="max-w-[560px] text-[14px] text-text-muted leading-[1.55]">
        {sub}
      </p>
      <p
        id={`${id}-phase`}
        className="mt-4 inline-block rounded-md border border-cortex-100 bg-cortex-50 px-2.5 py-1 font-mono text-[10px] text-cortex-500 uppercase tracking-widest"
      >
        {phase}
      </p>
    </div>
  );
}
