'use client';

import { useEffect, useState } from 'react';

/**
 * Returns a debounced copy of `value` that only updates after `delayMs` of
 * quiet. Used by list-search inputs so a server-side query fires once the
 * user pauses typing rather than on every keystroke.
 *
 * The first render returns `value` immediately (no initial debounce delay),
 * so the first paint matches the controlled input.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const handle = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(handle);
  }, [value, delayMs]);

  return debounced;
}
