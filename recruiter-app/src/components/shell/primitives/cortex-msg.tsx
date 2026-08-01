'use client';

import { Fragment, type ReactNode } from 'react';
import { BrandIcon } from '@/components/icons/brand-icons';
import { cn } from '@/lib/utils';
import type { CortexMessagePayload } from '@/types/sub-agent';
import type { AgentChip } from './agent-msg';

interface CortexMsgProps {
  id: string;
  payload: CortexMessagePayload;
  time?: string;
  onChip?: (chip: AgentChip) => void;
}

function renderInlineBold(text: string): ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, idx) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return (
        <strong
          // biome-ignore lint/suspicious/noArrayIndexKey: regex split parts are positionally stable per text run
          key={`b-${idx}-${part}`}
          className="font-semibold text-text-primary"
        >
          {part.slice(2, -2)}
        </strong>
      );
    }
    return (
      <Fragment
        // biome-ignore lint/suspicious/noArrayIndexKey: regex split parts are positionally stable per text run
        key={`t-${idx}-${part}`}
      >
        {part}
      </Fragment>
    );
  });
}

export function CortexMsg({ id, payload, time, onChip }: CortexMsgProps) {
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
          id={`${id}-who`}
          className="mb-1.5 flex items-center gap-2 font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]"
        >
          <span className="text-text-muted">{payload.who}</span>
          {time && <span>{time}</span>}
        </div>
        <div
          id={`${id}-bubble`}
          className="inline-block max-w-[620px] rounded-[14px] bg-surface px-4 py-3 font-sans text-[13.5px] text-text-primary leading-[1.55]"
        >
          <div id={`${id}-prose`} className="flex flex-col gap-2.5">
            {payload.blocks.map((block, idx) => {
              if (block.kind === 'paragraph') {
                return (
                  <p
                    // biome-ignore lint/suspicious/noArrayIndexKey: blocks are a fixed fixture list
                    key={`p-${idx}-${block.text.slice(0, 24)}`}
                    id={`${id}-block-${idx}`}
                    className="m-0"
                  >
                    {renderInlineBold(block.text)}
                  </p>
                );
              }
              if (block.kind === 'bullets') {
                return (
                  <ul
                    // biome-ignore lint/suspicious/noArrayIndexKey: blocks are a fixed fixture list
                    key={`u-${idx}`}
                    id={`${id}-block-${idx}`}
                    className="m-0 flex flex-col gap-2 pl-0"
                  >
                    {block.items.map((item, i) => (
                      <li
                        // biome-ignore lint/suspicious/noArrayIndexKey: bullet items are a fixed fixture list
                        key={`li-${i}-${item.slice(0, 20)}`}
                        className="flex gap-2"
                      >
                        <span
                          aria-hidden
                          className={cn(
                            'mt-[0.55em] h-[3px] w-[3px] shrink-0 rounded-full bg-text-muted',
                          )}
                        />
                        <span className="min-w-0 flex-1">{renderInlineBold(item)}</span>
                      </li>
                    ))}
                  </ul>
                );
              }
              // quote
              return (
                <figure
                  // biome-ignore lint/suspicious/noArrayIndexKey: blocks are a fixed fixture list
                  key={`q-${idx}-${block.text.slice(0, 20)}`}
                  id={`${id}-block-${idx}`}
                  className="m-0 border-[#0F1620]/70 border-l-[2px] py-0.5 pl-3"
                >
                  <blockquote className="m-0 font-display text-[14.5px] text-text-primary italic leading-[1.4] tracking-[-0.005em]">
                    &ldquo;{block.text}&rdquo;
                  </blockquote>
                  <figcaption className="mt-1 font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
                    {block.cite}
                  </figcaption>
                </figure>
              );
            })}
          </div>
        </div>
        {payload.chips && payload.chips.length > 0 && (
          <div id={`${id}-chips`} className="mt-3 flex flex-wrap gap-2">
            {payload.chips.map((c) => (
              <button
                key={c.value}
                id={`${id}-chip-${c.value}`}
                type="button"
                onClick={() => onChip?.(c)}
                className={cn(
                  'inline-flex items-center gap-2 rounded-full border px-3.5 py-2 font-medium font-sans text-[13px] shadow-[0_1px_2px_rgba(0,0,0,0.03)] transition-colors',
                  c.primary
                    ? 'border-text-primary bg-text-primary text-white hover:bg-[#222]'
                    : 'border-border/70 bg-white/70 text-text-primary backdrop-blur-sm hover:border-text-primary hover:bg-white/85',
                )}
              >
                <span>{c.label}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
