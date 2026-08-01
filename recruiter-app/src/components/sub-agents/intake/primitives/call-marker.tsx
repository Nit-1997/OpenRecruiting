'use client';

interface CallMarkerProps {
  id: string;
  label: string;
}

export function CallMarker({ id, label }: CallMarkerProps) {
  return (
    <div
      id={id}
      className="my-4 flex items-center gap-3 font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]"
    >
      <span id={`${id}-line-left`} aria-hidden className="h-px flex-1 bg-border" />
      <span id={`${id}-label`}>{label}</span>
      <span id={`${id}-line-right`} aria-hidden className="h-px flex-1 bg-border" />
    </div>
  );
}
