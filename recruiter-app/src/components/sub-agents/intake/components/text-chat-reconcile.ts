import type { Turn } from '@/types/intake';

export interface PendingUserTurn {
  /** Exact text the recruiter sent (trimmed). */
  text: string;
  /** Greatest turn idx present at send time — the real turn must exceed this. */
  baseMaxIdx: number;
}

/**
 * True while the optimistic user bubble should still be shown — i.e. the real
 * persisted user turn has not yet arrived in `turns`. We require idx > baseMaxIdx
 * so an identical earlier message doesn't make a fresh send vanish instantly.
 */
export function shouldShowPending(turns: Turn[], pending: PendingUserTurn | null): boolean {
  if (!pending) return false;
  const landed = turns.some(
    (t) => t.role === 'user' && t.idx > pending.baseMaxIdx && t.content === pending.text,
  );
  return !landed;
}
