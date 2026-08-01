import type React from 'react';
import type { AnswerStatus } from '@/types/intake';

type GoalStatusEntry = {
  label: string;
  dot: string;
  glyph: 'check' | 'dot' | 'pulse' | 'ring' | 'dash';
};

export const GOAL_STATUS: Record<AnswerStatus, GoalStatusEntry> = {
  validated: { label: 'Confirmed', dot: 'var(--status-success-fg)', glyph: 'check' },
  discussed: { label: 'Captured', dot: 'var(--cortex-500)', glyph: 'dot' },
  needs_probe: { label: 'In progress', dot: 'var(--status-warn-fg)', glyph: 'pulse' },
  untouched: { label: 'Not yet', dot: 'var(--text-faint)', glyph: 'ring' },
  skipped: { label: 'Skipped', dot: 'var(--text-faint)', glyph: 'dash' },
};

interface StatusMarkProps {
  status: AnswerStatus;
  size?: number;
}

export function StatusMark({ status, size = 18 }: StatusMarkProps) {
  const s = GOAL_STATUS[status] ?? GOAL_STATUS.untouched;

  if (s.glyph === 'check') {
    const checkWrapStyle: React.CSSProperties = {
      width: size,
      height: size,
      borderRadius: '50%',
      background: s.dot,
      display: 'grid',
      placeItems: 'center',
      flexShrink: 0,
    };
    const checkIconSize = size * 0.66;
    return (
      <span style={checkWrapStyle}>
        <svg
          width={checkIconSize}
          height={checkIconSize}
          viewBox="0 0 24 24"
          fill="none"
          stroke="#fff"
          strokeWidth={3}
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
          style={{ display: 'block', flexShrink: 0 }}
        >
          <path d="M20 6 9 17l-5-5" />
        </svg>
      </span>
    );
  }

  if (s.glyph === 'pulse') {
    const pulseStyle: React.CSSProperties & { '--pd'?: string } = {
      width: size,
      height: size,
      '--pd': s.dot,
    };
    return <span className="mz-pulse-dot" style={pulseStyle} />;
  }

  if (s.glyph === 'dot') {
    const dotStyle: React.CSSProperties = {
      width: size,
      height: size,
      borderRadius: '50%',
      background: s.dot,
      flexShrink: 0,
      display: 'inline-block',
    };
    return <span style={dotStyle} />;
  }

  const ringStyle: React.CSSProperties = {
    width: size,
    height: size,
    borderRadius: '50%',
    border: '1.5px solid var(--border)',
    flexShrink: 0,
    display: 'inline-block',
  };
  return <span style={ringStyle} />;
}
