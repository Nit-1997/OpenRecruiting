'use client';

interface ThinkingPillProps {
  id: string;
  label?: string;
}

export function ThinkingPill({ id, label = 'Thinking' }: ThinkingPillProps) {
  return (
    <div
      id={id}
      className="relative ml-11 inline-flex items-center gap-2.5 self-start overflow-hidden rounded-full border border-border bg-paper px-3 py-1.5 text-[12px] text-text-muted"
      style={{ animation: 'rise 220ms var(--ease-out) both' }}
    >
      <span
        id={`${id}-orb`}
        aria-hidden
        className="h-2.5 w-2.5 shrink-0 rounded-full"
        style={{
          background: 'radial-gradient(circle at 30% 30%, #E7E2FF 0%, #B9B0E8 40%, #5E4FAE 100%)',
          animation: 'mz-breathe 1.4s cubic-bezier(0.4, 0, 0.2, 1) infinite',
        }}
      />
      <span id={`${id}-label`} className="relative z-10">
        {label}
      </span>
      <span id={`${id}-dots`} aria-hidden className="relative z-10 flex items-center gap-[3px]">
        <span
          className="h-1 w-1 rounded-full bg-cortex-500"
          style={{
            animation: 'mz-breathe 1.4s cubic-bezier(0.4, 0, 0.2, 1) infinite',
            animationDelay: '0ms',
          }}
        />
        <span
          className="h-1 w-1 rounded-full bg-cortex-500"
          style={{
            animation: 'mz-breathe 1.4s cubic-bezier(0.4, 0, 0.2, 1) infinite',
            animationDelay: '140ms',
          }}
        />
        <span
          className="h-1 w-1 rounded-full bg-cortex-500"
          style={{
            animation: 'mz-breathe 1.4s cubic-bezier(0.4, 0, 0.2, 1) infinite',
            animationDelay: '280ms',
          }}
        />
      </span>
      <span aria-hidden className="mz-shimmer-overlay" />
    </div>
  );
}
