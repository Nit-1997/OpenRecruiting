'use client';

import { ChevronUp, Mic, Minus, PhoneOff, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useVoiceStore } from '@/stores';

interface VoicePopoutProps {
  id: string;
}

function formatSeconds(total: number): string {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export function VoicePopout({ id }: VoicePopoutProps) {
  const active = useVoiceStore((s) => s.active);
  const minimized = useVoiceStore((s) => s.minimized);
  const seconds = useVoiceStore((s) => s.seconds);
  const captions = useVoiceStore((s) => s.captions);
  const ownerTabId = useVoiceStore((s) => s.ownerTabId);
  const end = useVoiceStore((s) => s.end);
  const minimize = useVoiceStore((s) => s.minimize);

  if (!active) return null;
  // Intake owns a full-screen call overlay; suppress the small popout there.
  if (ownerTabId === 'intake') return null;

  const latestCaption =
    captions.at(-1) ?? "Tell me about the role — team, level, what they'll own.";

  if (minimized) {
    return (
      <button
        id={id}
        type="button"
        onClick={minimize}
        aria-label="Restore voice popout"
        className="fixed right-20 bottom-24 z-40 inline-flex items-center gap-3 rounded-full border border-border bg-white px-3.5 py-2 shadow-[0_8px_28px_rgba(0,0,0,0.08)] transition-transform hover:-translate-y-0.5"
      >
        <span
          id={`${id}-orb`}
          aria-hidden
          className="h-6 w-6 rounded-full"
          style={{
            background:
              'radial-gradient(circle at 30% 30%, #E7E2FF 0%, #B9B0E8 40%, #5E4FAE 75%, #2E2350 100%)',
          }}
        />
        <span
          id={`${id}-timer`}
          className="font-mono text-[12px] text-text-secondary tracking-wider"
        >
          {formatSeconds(seconds)}
        </span>
        <span id={`${id}-chevron`} aria-hidden className="text-text-muted">
          <ChevronUp strokeWidth={1.75} className="h-3.5 w-3.5" />
        </span>
      </button>
    );
  }

  return (
    <div
      id={id}
      role="dialog"
      aria-label="Voice call"
      className={cn(
        'fixed right-20 bottom-24 z-40 flex w-[320px] flex-col overflow-hidden rounded-[18px] border border-border bg-white shadow-[0_12px_36px_rgba(0,0,0,0.1)]',
      )}
    >
      <div
        id={`${id}-head`}
        className="flex items-center gap-2 border-border border-b bg-bg px-3.5 py-2.5"
      >
        <span
          id={`${id}-dot`}
          aria-hidden
          className="h-1.5 w-1.5 animate-pulse rounded-full bg-cortex-500"
        />
        <span id={`${id}-title`} className="font-medium font-sans text-[12.5px] text-text-primary">
          On call with OpenRecruiting
        </span>
        <span
          id={`${id}-timer`}
          className="ml-auto font-mono text-[11px] text-text-secondary tracking-wider"
        >
          {formatSeconds(seconds)}
        </span>
        <button
          id={`${id}-minimize`}
          type="button"
          aria-label="Minimize call"
          onClick={minimize}
          className="flex h-6 w-6 items-center justify-center rounded-full text-text-muted transition-colors hover:bg-surface hover:text-text-primary"
        >
          <Minus strokeWidth={1.75} className="h-3 w-3" />
        </button>
        <button
          id={`${id}-close`}
          type="button"
          aria-label="End call"
          onClick={end}
          className="flex h-6 w-6 items-center justify-center rounded-full text-text-muted transition-colors hover:bg-surface hover:text-text-primary"
        >
          <X strokeWidth={1.75} className="h-3 w-3" />
        </button>
      </div>

      <div id={`${id}-body`} className="flex flex-col items-center gap-3 px-4 pt-5 pb-3">
        <div
          id={`${id}-orb`}
          aria-hidden
          className="h-[72px] w-[72px] animate-pulse rounded-full"
          style={{
            background:
              'radial-gradient(circle at 30% 30%, #E7E2FF 0%, #B9B0E8 40%, #5E4FAE 75%, #2E2350 100%)',
            animationDuration: '1.6s',
          }}
        />
        <div
          id={`${id}-meta`}
          className="flex items-center gap-2 font-mono text-[11px] text-text-muted uppercase tracking-[0.14em]"
        >
          <span>OpenRecruiting is listening</span>
          <span aria-hidden className="text-text-faint">
            · voice
          </span>
        </div>
      </div>

      <div id={`${id}-captions`} className="border-border border-t px-4 py-3">
        <p id={`${id}-caption`} className="text-[12.5px] text-text-secondary leading-[1.5]">
          {latestCaption}
        </p>
      </div>

      <div
        id={`${id}-foot`}
        className="flex items-center justify-between border-border border-t px-3 py-2.5"
      >
        <button
          id={`${id}-mute`}
          type="button"
          aria-label="Mute"
          className="flex h-8 w-8 items-center justify-center rounded-full border border-border text-text-muted transition-colors hover:border-text-primary hover:text-text-primary"
        >
          <Mic strokeWidth={1.75} className="h-3.5 w-3.5" />
        </button>
        <button
          id={`${id}-end`}
          type="button"
          aria-label="End call"
          onClick={end}
          className="flex h-8 items-center gap-2 rounded-full bg-[#DC2626] px-3 font-medium text-[12px] text-white transition-colors hover:bg-[#b91c1c]"
        >
          <PhoneOff strokeWidth={1.75} className="h-3.5 w-3.5" />
          End
        </button>
      </div>
    </div>
  );
}
