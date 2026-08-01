import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Pick a foreground color (near-black or white) for text rendered on top of
 * an avatar / chip background, using WCAG relative luminance. Inline styles
 * win over theme-flipped class colors, so this stays correct in light AND
 * dark mode whether the bg is a pastel (#EADFD4) or a saturated brand hex
 * (#D64B1A, #111). Accepts #rgb / #rrggbb; returns '#111111' or '#ffffff'.
 */
export function pickAvatarFg(bg: string): string {
  const h = bg.replace('#', '').trim();
  const norm =
    h.length === 3
      ? h
          .split('')
          .map((c) => c + c)
          .join('')
      : h;
  if (norm.length !== 6) return '#111111';
  const r = Number.parseInt(norm.slice(0, 2), 16);
  const g = Number.parseInt(norm.slice(2, 4), 16);
  const b = Number.parseInt(norm.slice(4, 6), 16);
  if ([r, g, b].some((v) => Number.isNaN(v))) return '#111111';
  const lin = (c: number) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  const L = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return L > 0.55 ? '#111111' : '#ffffff';
}
