import type React from 'react';

interface ProgressRingProps {
  value: number;
  total: number;
  size?: number;
  stroke?: number;
  label?: boolean;
}

export function ProgressRing({
  value,
  total,
  size = 56,
  stroke = 4,
  label = true,
}: ProgressRingProps) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  // Coerce non-finite props (e.g. a list row that predates the enriched
  // backend fields) so we never emit NaN to strokeDashoffset.
  const safeValue = Number.isFinite(value) ? value : 0;
  const safeTotal = Number.isFinite(total) && total > 0 ? total : 0;
  const pct = safeTotal ? Math.min(1, Math.max(0, safeValue / safeTotal)) : 0;

  const labelStyle: React.CSSProperties = {
    position: 'absolute',
    inset: 0,
    display: 'grid',
    placeItems: 'center',
    fontFamily: 'var(--font-mono)',
    fontSize: size * 0.26,
    color: 'var(--text-primary)',
    fontVariantNumeric: 'tabular-nums',
  };

  return (
    <div style={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} aria-hidden="true" style={{ transform: 'rotate(-90deg)' }}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--border)"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--cortex-500)"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - pct)}
          style={{ transition: 'stroke-dashoffset 700ms var(--ease-out)' }}
        />
      </svg>
      {label && (
        <div style={labelStyle}>
          {safeValue}
          <span style={{ color: 'var(--text-faint)' }}>/{safeTotal}</span>
        </div>
      )}
    </div>
  );
}
