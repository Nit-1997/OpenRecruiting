import type { JSX } from 'react';

interface Props {
  id: string;
  ariaLabel: string;
  disabled?: boolean;
  /** All drag-handle attributes (onPointerDown, etc.) from the parent's drag library. */
  dragHandleProps?: React.HTMLAttributes<HTMLButtonElement>;
}

export function RoundReorderHandle({
  id,
  ariaLabel,
  disabled,
  dragHandleProps,
}: Props): JSX.Element {
  return (
    <button
      {...dragHandleProps}
      id={id}
      type="button"
      aria-label={ariaLabel}
      disabled={disabled ?? false}
      className="touch-none cursor-grab active:cursor-grabbing p-1 text-slate-500 hover:text-slate-300 disabled:cursor-not-allowed disabled:opacity-40"
    >
      <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor" aria-hidden>
        <circle cx="4" cy="3" r="1.2" />
        <circle cx="4" cy="7" r="1.2" />
        <circle cx="4" cy="11" r="1.2" />
        <circle cx="10" cy="3" r="1.2" />
        <circle cx="10" cy="7" r="1.2" />
        <circle cx="10" cy="11" r="1.2" />
      </svg>
    </button>
  );
}
