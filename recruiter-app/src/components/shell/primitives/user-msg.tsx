'use client';

import { MessageSquare, Mic } from 'lucide-react';
import { cn } from '@/lib/utils';

interface UserMsgProps {
  id: string;
  text: string;
  mode?: 'text' | 'voice';
  time?: string;
}

export function UserMsg({ id, text, mode = 'text', time }: UserMsgProps) {
  const Icon = mode === 'voice' ? Mic : MessageSquare;
  return (
    <div id={id} className="flex flex-col items-end gap-1 self-end">
      <div
        id={`${id}-bubble`}
        className={cn(
          'inline-flex max-w-[560px] items-center gap-2 rounded-[14px] border border-transparent px-3.5 py-2 text-[13.5px] text-text-primary',
          mode === 'voice' ? 'bg-cortex-50' : 'bg-surface',
        )}
      >
        <span id={`${id}-ic`} aria-hidden className="text-text-muted">
          <Icon strokeWidth={1.75} className="h-3.5 w-3.5" />
        </span>
        <span id={`${id}-text`}>{text}</span>
      </div>
      {time && (
        <span
          id={`${id}-time`}
          className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]"
        >
          {time}
        </span>
      )}
    </div>
  );
}
