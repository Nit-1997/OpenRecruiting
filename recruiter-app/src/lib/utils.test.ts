import { describe, expect, test } from 'bun:test';
import { cn, pickAvatarFg } from './utils';

describe('cn', () => {
  test('merges class names', () => {
    expect(cn('a', 'b')).toBe('a b');
  });

  test('skips falsy entries', () => {
    expect(cn('a', false, null, undefined, 'b')).toBe('a b');
  });

  test('dedupes/wins later tailwind classes (twMerge contract)', () => {
    // twMerge collapses conflicting Tailwind utilities — later wins.
    expect(cn('p-2', 'p-4')).toBe('p-4');
    expect(cn('text-sm', 'text-lg')).toBe('text-lg');
  });

  test('keeps unrelated utilities side-by-side', () => {
    expect(cn('flex', 'items-center', 'gap-2')).toContain('flex');
    expect(cn('flex', 'items-center', 'gap-2')).toContain('items-center');
    expect(cn('flex', 'items-center', 'gap-2')).toContain('gap-2');
  });

  test('accepts conditional object syntax (clsx contract)', () => {
    expect(cn({ active: true, disabled: false })).toBe('active');
  });
});

describe('pickAvatarFg', () => {
  test('returns near-black on light background', () => {
    expect(pickAvatarFg('#ffffff')).toBe('#111111');
    expect(pickAvatarFg('#EADFD4')).toBe('#111111'); // pastel
    expect(pickAvatarFg('#FBE9D8')).toBe('#111111');
  });

  test('returns white on dark background', () => {
    expect(pickAvatarFg('#000000')).toBe('#ffffff');
    expect(pickAvatarFg('#111111')).toBe('#ffffff');
    expect(pickAvatarFg('#1D4ED8')).toBe('#ffffff'); // saturated blue
    expect(pickAvatarFg('#D64B1A')).toBe('#ffffff'); // brand orange
  });

  test('accepts 3-digit shorthand hex', () => {
    expect(pickAvatarFg('#fff')).toBe('#111111');
    expect(pickAvatarFg('#000')).toBe('#ffffff');
    expect(pickAvatarFg('#fa3')).toBeDefined();
  });

  test('accepts hex without the leading #', () => {
    expect(pickAvatarFg('111111')).toBe('#ffffff');
    expect(pickAvatarFg('ffffff')).toBe('#111111');
  });

  test('returns the safe default for malformed inputs', () => {
    expect(pickAvatarFg('')).toBe('#111111');
    expect(pickAvatarFg('#zz')).toBe('#111111');
    expect(pickAvatarFg('not-a-color')).toBe('#111111');
    expect(pickAvatarFg('#GGGGGG')).toBe('#111111');
  });
});
