'use client';

import { ArrowUpRight, LayoutGrid } from 'lucide-react';
import { BrandIcon } from '@/components/icons/brand-icons';
import { Card } from '@/components/ui/card';

interface DebriefPacketPillProps {
  id: string;
  roleTitle: string;
  onOpen: () => void;
  time?: string;
}

/**
 * Inline debrief-packet reference card. Appended to the transcript when a
 * packet finishes generating, it stays in the chat history permanently — so
 * closing the workspace panel (or starting a later session and loading earlier
 * history) never strands the packet. "Open packet" re-points the workspace at
 * the in-store artifact, refetching the packet by id when the store no longer
 * has it (e.g. after a reload). Purely presentational — the flow owns reopening.
 */
export function DebriefPacketPill({ id, roleTitle, onOpen, time }: DebriefPacketPillProps) {
  return (
    <div id={id} className="flex max-w-[760px] items-start gap-3.5 py-2">
      <div
        id={`${id}-avatar`}
        aria-hidden
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white"
      >
        <BrandIcon className="h-6 w-6 text-text-primary" />
      </div>
      <div id={`${id}-body`} className="min-w-0 flex-1">
        <div
          id={`${id}-meta`}
          className="mb-1.5 flex items-center gap-2 font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]"
        >
          <span className="text-text-muted">openrecruiting debrief · packet</span>
          {time && <span>{time}</span>}
        </div>

        <Card id={`${id}-card`} className="max-w-[560px]">
          <div id={`${id}-row`} className="flex items-center justify-between gap-3">
            <div id={`${id}-label-wrap`} className="flex min-w-0 items-center gap-2.5">
              <LayoutGrid
                strokeWidth={1.75}
                className="h-4 w-4 shrink-0 text-text-muted"
                aria-hidden
              />
              <div id={`${id}-label`} className="min-w-0">
                <h4
                  id={`${id}-title`}
                  className="truncate font-medium text-[14px] text-charcoal leading-snug"
                >
                  Comparative debrief · {roleTitle}
                </h4>
                <p id={`${id}-sub`} className="mt-0.5 text-[12px] text-text-muted leading-snug">
                  Click to reopen the packet in the workspace.
                </p>
              </div>
            </div>
            <button
              id={`${id}-open`}
              type="button"
              onClick={onOpen}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-border/70 bg-white/70 px-3 py-1.5 font-medium font-sans text-[12.5px] text-text-primary transition-colors hover:border-text-primary hover:bg-white"
            >
              <ArrowUpRight strokeWidth={1.75} className="h-3.5 w-3.5" aria-hidden />
              <span>Open packet</span>
            </button>
          </div>
        </Card>
      </div>
    </div>
  );
}
