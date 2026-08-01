import type React from 'react';

type OrbState = 'idle' | 'connecting' | 'listening' | 'speaking';

interface OrbProps {
  size?: number;
  state?: OrbState;
  motion?: boolean;
}

export function Orb({ size = 132, state = 'listening', motion = true }: OrbProps) {
  const live = state === 'listening' || state === 'speaking';
  const speaking = state === 'speaking';

  const coreStyle: React.CSSProperties = {
    width: size * 0.3,
    height: size * 0.3,
    borderRadius: '50%',
    background: 'var(--cortex-orb)',
    boxShadow: live ? '0 0 28px 4px var(--orb-glow)' : 'none',
  };

  return (
    <div
      className="mz-orb"
      style={{
        width: size,
        height: size,
        position: 'relative',
        display: 'grid',
        placeItems: 'center',
      }}
      data-state={state}
    >
      {motion && live && (
        <>
          <span className="mz-orb-ripple" style={{ animationDelay: '0s' }} />
          <span className="mz-orb-ripple" style={{ animationDelay: '1.4s' }} />
        </>
      )}
      <svg
        width={size}
        height={size}
        viewBox="0 0 100 100"
        aria-hidden="true"
        style={{ position: 'absolute', inset: 0 }}
      >
        <circle
          cx="50"
          cy="50"
          r="46"
          fill="none"
          stroke="var(--periwinkle-soft)"
          strokeWidth="1"
          opacity={live ? 0.55 : 0.3}
        />
        <circle
          cx="50"
          cy="50"
          r="33"
          fill="none"
          stroke="var(--periwinkle)"
          strokeWidth="1.25"
          opacity={live ? 0.7 : 0.35}
        />
      </svg>
      <div
        className={motion && live ? 'mz-orb-core mz-orb-breathe' : 'mz-orb-core'}
        style={coreStyle}
      />
      {speaking && motion && (
        <div className="mz-orb-eq" aria-hidden="true">
          {[0, 1, 2, 3, 4].map((i) => (
            <span key={i} style={{ animationDelay: `${i * 0.12}s` }} />
          ))}
        </div>
      )}
    </div>
  );
}
