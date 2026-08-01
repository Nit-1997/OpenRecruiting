import type { SVGProps } from 'react';

const PIXELS = { sm: 16, md: 20, lg: 28 } as const;

export interface AgentMarkProps extends SVGProps<SVGSVGElement> {
  id: string;
  size?: keyof typeof PIXELS;
}

export function AgentMark({ id, size = 'md', className, ...props }: AgentMarkProps) {
  const px = PIXELS[size];
  return (
    <svg
      id={id}
      width={px}
      height={px}
      viewBox="0 0 32 32"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      role="img"
      aria-label="OpenRecruiting agent"
      {...props}
    >
      <circle cx="16" cy="16" r="14" fill="transparent" stroke="var(--color-accent-agent)" strokeWidth="1.5" />
      <path
        data-agent-fill
        d="M16 2 a 14 14 0 0 1 0 28 z"
        fill="var(--color-accent-agent)"
      />
    </svg>
  );
}
