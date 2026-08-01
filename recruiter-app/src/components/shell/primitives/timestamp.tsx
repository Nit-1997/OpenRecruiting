'use client';

interface TimestampProps {
  id: string;
  label: string;
}

export function Timestamp({ id, label }: TimestampProps) {
  return (
    <div
      id={id}
      className="mx-auto my-2.5 inline-flex items-center gap-2.5 self-center font-mono text-[10px] text-text-faint uppercase tracking-[0.2em]"
    >
      <span id={`${id}-l`} className="inline-block h-px w-7 bg-border" aria-hidden />
      <span id={`${id}-label`}>{label}</span>
      <span id={`${id}-r`} className="inline-block h-px w-7 bg-border" aria-hidden />
    </div>
  );
}
