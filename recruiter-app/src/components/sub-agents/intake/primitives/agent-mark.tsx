interface AgentMarkProps {
  size?: number;
  color?: string;
}

export function AgentMark({ size = 22, color = 'currentColor' }: AgentMarkProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 120 120"
      aria-hidden="true"
      style={{ display: 'block' }}
    >
      <defs>
        <path
          id="mz-blade"
          d="M 0 -12.5 L 0 -45 A 12.5 12.5 0 0 1 25 -45 L 25 -12.5 A 12.5 12.5 0 0 1 0 -12.5 Z"
        />
      </defs>
      <g transform="translate(60,60)" fill={color}>
        <use href="#mz-blade" transform="rotate(-150) translate(0,10)" />
        <use href="#mz-blade" transform="rotate(-30) translate(0,10)" />
        <use href="#mz-blade" transform="rotate(90) translate(0,10)" />
        <circle cx="0" cy="0" r="11" />
      </g>
    </svg>
  );
}
