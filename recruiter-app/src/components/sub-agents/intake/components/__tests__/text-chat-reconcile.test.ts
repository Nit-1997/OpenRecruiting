import { describe, expect, it } from 'bun:test';
import type { Turn } from '@/types/intake';
import { shouldShowPending } from '../text-chat-reconcile';

function userTurn(idx: number, content: string): Turn {
  return { idx, role: 'user', content, modality: 'text', timestamp: '2026-05-30T00:00:00Z' };
}

describe('shouldShowPending', () => {
  it('returns false when there is no pending message', () => {
    expect(shouldShowPending([], null)).toBe(false);
  });

  it('shows pending while no matching real turn has landed yet', () => {
    const turns = [userTurn(0, 'earlier')];
    expect(shouldShowPending(turns, { text: 'hello', baseMaxIdx: 0 })).toBe(true);
  });

  it('hides pending once the real user turn (idx > baseMaxIdx, same content) lands', () => {
    const turns = [userTurn(0, 'earlier'), userTurn(1, 'hello')];
    expect(shouldShowPending(turns, { text: 'hello', baseMaxIdx: 0 })).toBe(false);
  });

  it('keeps showing pending when the only matching turn predates the send (idx <= baseMaxIdx)', () => {
    const turns = [userTurn(0, 'hello')];
    expect(shouldShowPending(turns, { text: 'hello', baseMaxIdx: 0 })).toBe(true);
  });
});
