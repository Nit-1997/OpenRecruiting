import type React from 'react';

interface WaveformProps {
  bars?: number;
  active?: boolean;
  motion?: boolean;
  height?: number;
  color?: string;
}

export function Waveform({
  bars = 28,
  active = true,
  motion = true,
  height = 22,
  color = 'var(--periwinkle)',
}: WaveformProps) {
  return (
    <div className="mz-wave" style={{ height }} aria-hidden="true">
      {Array.from({ length: bars }, (_, i) => {
        const barStyle: React.CSSProperties = {
          background: color,
          animationDelay: `${(i % 7) * 0.09}s`,
          height: active ? undefined : `${20 + ((i * 37) % 50)}%`,
        };
        return (
          <span
            // biome-ignore lint/suspicious/noArrayIndexKey: bars are positional fixed-count, never reordered
            key={`bar-${i}`}
            className={motion && active ? 'mz-wave-bar mz-wave-anim' : 'mz-wave-bar'}
            style={barStyle}
          />
        );
      })}
    </div>
  );
}
