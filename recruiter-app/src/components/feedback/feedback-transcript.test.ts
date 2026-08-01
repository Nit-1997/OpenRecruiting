import { describe, expect, test } from 'bun:test';
import {
  appendBotTurn,
  appendUserTurn,
  cleanBotText,
  normalizeUserText,
  type TranscriptTurn,
} from './feedback-transcript';

describe('normalizeUserText', () => {
  test('fixes the misheard agent name and trims', () => {
    expect(normalizeUserText('  I told mayzel about it ')).toBe('I told OpenRecruiting about it');
  });
  test('empty/whitespace collapses to empty string', () => {
    expect(normalizeUserText('   ')).toBe('');
  });
  test('does not over-match inside a larger word (word boundaries)', () => {
    expect(normalizeUserText('mayzelle')).toBe('mayzelle');
    expect(normalizeUserText('mayzels')).toBe('mayzels');
  });
});

describe('cleanBotText', () => {
  test('strips [END] and [interrupted...] markers and fixes name', () => {
    expect(cleanBotText('Thanks, mayzle here. [interrupted by user][END]')).toBe(
      'Thanks, OpenRecruiting here.',
    );
  });
});

describe('appendUserTurn', () => {
  test('appends a normalized user turn', () => {
    const out = appendUserTurn([], 'hello there');
    expect(out).toEqual([{ role: 'user', text: 'hello there' }]);
  });
  test('skips empty text (returns same array reference)', () => {
    const prev: TranscriptTurn[] = [{ role: 'user', text: 'x' }];
    expect(appendUserTurn(prev, '   ')).toBe(prev);
  });
});

describe('appendBotTurn', () => {
  test('cleans then appends a bot turn', () => {
    expect(appendBotTurn([], 'Got it [END]')).toEqual([{ role: 'bot', text: 'Got it' }]);
  });
  test('skips empty after cleaning (returns same array reference)', () => {
    const prev: TranscriptTurn[] = [{ role: 'bot', text: 'hi' }];
    expect(appendBotTurn(prev, '[END]')).toBe(prev);
  });
  test('dedupes a consecutive identical bot turn', () => {
    const prev: TranscriptTurn[] = [{ role: 'bot', text: 'hi' }];
    expect(appendBotTurn(prev, 'hi')).toBe(prev);
  });
});
