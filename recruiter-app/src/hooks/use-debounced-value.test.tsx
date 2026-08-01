import { afterEach, describe, expect, test } from 'bun:test';
import { act, cleanup, render, waitFor } from '@testing-library/react';
import { useDebouncedValue } from './use-debounced-value';

afterEach(cleanup);

function Harness({
  value,
  delay,
  expose,
}: {
  value: string;
  delay: number;
  expose: (v: string) => void;
}) {
  const debounced = useDebouncedValue(value, delay);
  expose(debounced);
  return null;
}

describe('useDebouncedValue', () => {
  test('returns the initial value immediately on first render', () => {
    let seen = '';
    render(<Harness value="hello" delay={20} expose={(v) => (seen = v)} />);
    expect(seen).toBe('hello');
  });

  test('only surfaces the latest value after the debounce delay (collapses rapid changes)', async () => {
    let seen = '';
    const { rerender } = render(<Harness value="a" delay={20} expose={(v) => (seen = v)} />);

    await act(async () => {
      rerender(<Harness value="ab" delay={20} expose={(v) => (seen = v)} />);
      rerender(<Harness value="abc" delay={20} expose={(v) => (seen = v)} />);
    });

    // Latest value eventually wins; intermediate "ab" is dropped.
    await waitFor(() => {
      expect(seen).toBe('abc');
    });
  });
});
