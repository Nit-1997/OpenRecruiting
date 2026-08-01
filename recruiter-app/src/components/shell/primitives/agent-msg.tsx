'use client';

import { ArrowUpRight, MessageSquare, Phone, Plus, Sparkles, Upload } from 'lucide-react';
import type { ReactNode } from 'react';
import { BrandIcon } from '@/components/icons/brand-icons';
import { cn } from '@/lib/utils';
import { renderMarkdown } from './markdown';

export interface AgentChip {
  label: string;
  value: string;
  primary?: boolean;
  icon?: ReactNode;
}

function defaultIconForValue(value: string): ReactNode | null {
  switch (value) {
    case 'call':
      return <Phone strokeWidth={1.75} className="h-3.5 w-3.5" />;
    case 'chat':
      return <MessageSquare strokeWidth={1.75} className="h-3.5 w-3.5" />;
    case 'upload':
      return <Upload strokeWidth={1.75} className="h-3.5 w-3.5" />;
    case 'open_manage':
      return <ArrowUpRight strokeWidth={1.75} className="h-3.5 w-3.5" />;
    case 'start_another':
      return <Plus strokeWidth={1.75} className="h-3.5 w-3.5" />;
    case 'publish_now':
      return <Sparkles strokeWidth={1.75} className="h-3.5 w-3.5" />;
    default:
      return null;
  }
}

interface AgentMsgProps {
  id: string;
  children: ReactNode;
  variant?: 'display' | 'small';
  name?: string;
  time?: string;
  sub?: ReactNode;
  chips?: AgentChip[];
  onChip?: (chip: AgentChip) => void;
  showMeta?: boolean;
}

export function AgentMsg({
  id,
  children,
  variant = 'display',
  name = 'OpenRecruiting',
  time,
  sub,
  chips,
  onChip,
  showMeta = true,
}: AgentMsgProps) {
  const isSmall = variant === 'small';
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
        {showMeta && (
          <div
            id={`${id}-meta`}
            className="mb-1 flex items-center gap-2 font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]"
          >
            <span id={`${id}-name`} className="text-text-muted">
              {name}
            </span>
            {time && <span id={`${id}-time`}>{time}</span>}
          </div>
        )}
        {isSmall ? (
          <div
            id={`${id}-bubble`}
            className="inline-block max-w-[620px] rounded-[14px] bg-surface px-3.5 py-2.5 font-sans text-[13.5px] text-text-primary leading-[1.55]"
          >
            <div id={`${id}-prose`}>{renderMarkdown(children)}</div>
          </div>
        ) : (
          <div
            id={`${id}-prose`}
            className="font-display font-normal text-[26px] leading-[1.35] tracking-[-0.005em]"
          >
            {renderMarkdown(children)}
          </div>
        )}
        {sub && (
          <div
            id={`${id}-sub`}
            className="mt-2 font-sans text-[13px] text-text-muted leading-[1.5]"
          >
            {sub}
          </div>
        )}
        {chips && chips.length > 0 && (
          <div id={`${id}-chips`} className="mt-3 flex flex-wrap gap-2">
            {chips.map((c) => {
              const icon = c.icon ?? defaultIconForValue(c.value);
              return (
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
                  {icon && <span aria-hidden>{icon}</span>}
                  <span>{c.label}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
