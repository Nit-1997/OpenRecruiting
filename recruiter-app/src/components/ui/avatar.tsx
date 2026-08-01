import type { HTMLAttributes } from 'react';
import { forwardRef, useMemo } from 'react';
import { cn } from '@/lib/utils';

const PALETTES = [
  { bg: 'bg-violet-100', text: 'text-violet-700' },
  { bg: 'bg-sky-100', text: 'text-sky-700' },
  { bg: 'bg-rose-100', text: 'text-rose-700' },
  { bg: 'bg-amber-100', text: 'text-amber-700' },
  { bg: 'bg-emerald-100', text: 'text-emerald-700' },
  { bg: 'bg-fuchsia-100', text: 'text-fuchsia-700' },
  { bg: 'bg-teal-100', text: 'text-teal-700' },
  { bg: 'bg-orange-100', text: 'text-orange-700' },
] as const;

function hashName(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i += 1) {
    h = ((h << 5) - h + name.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/);
  const first = parts[0];
  const last = parts[parts.length - 1];
  if (parts.length >= 2 && first && last) {
    return (first[0]! + last[0]!).toUpperCase();
  }
  const single = name.trim();
  if (single.length === 1) {
    return (single + single).toUpperCase();
  }
  return single.slice(0, 2).toUpperCase();
}

export interface AvatarProps extends HTMLAttributes<HTMLSpanElement> {
  id: string;
  name: string;
  size?: 'sm' | 'md' | 'lg';
  src?: string;
}

export const Avatar = forwardRef<HTMLSpanElement, AvatarProps>(
  ({ id, name, size = 'md', src, className, ...props }, ref) => {
    const palette = useMemo(() => PALETTES[hashName(name) % PALETTES.length]!, [name]);
    const initials = useMemo(() => getInitials(name), [name]);
    const sizeClass = size === 'sm' ? 'size-6 text-[10px]' : size === 'lg' ? 'size-10 text-sm' : 'size-8 text-[11px]';
    return (
      <span
        id={id}
        ref={ref}
        aria-label={name}
        className={cn(
          'inline-flex items-center justify-center rounded-full font-sans font-semibold overflow-hidden shrink-0',
          sizeClass,
          !src && palette.bg,
          !src && palette.text,
          className,
        )}
        {...props}
      >
        {src ? (
          <img id={`${id}-img`} src={src} alt={name} className="h-full w-full object-cover" />
        ) : (
          <span id={`${id}-initials`}>{initials}</span>
        )}
      </span>
    );
  },
);
Avatar.displayName = 'Avatar';
