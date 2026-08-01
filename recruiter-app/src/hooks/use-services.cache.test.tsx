import { afterEach, describe, expect, test } from 'bun:test';
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import { __asyncCache, clearAsyncCache, useAsyncList } from './use-services';

afterEach(() => {
  cleanup();
  clearAsyncCache();
});

describe('useAsyncList SWR cache', () => {
  test('cold mount goes null -> loading -> data; warm remount paints cached data synchronously', async () => {
    let calls = 0;
    const loader = async () => {
      calls += 1;
      return [`v${calls}`];
    };

    // Cold mount
    const first = renderHook(() => useAsyncList<string[]>(loader, [], [], { cacheKey: 'k1' }));
    expect(first.result.current.data).toBeNull();
    expect(first.result.current.loading).toBe(true);
    await waitFor(() => expect(first.result.current.loading).toBe(false));
    expect(first.result.current.data).toEqual(['v1']);
    cleanup();

    // Warm remount: cached data is present on the FIRST render, before revalidate resolves
    const second = renderHook(() => useAsyncList<string[]>(loader, [], [], { cacheKey: 'k1' }));
    expect(second.result.current.data).toEqual(['v1']); // instant, from cache
    expect(second.result.current.loading).toBe(true); // revalidating in background
    await waitFor(() => expect(second.result.current.data).toEqual(['v2']));
  });

  test('revalidate error keeps stale cached data instead of blanking', async () => {
    let calls = 0;
    const loader = async () => {
      calls += 1;
      if (calls >= 2) throw new Error('boom');
      return ['ok'];
    };
    const first = renderHook(() => useAsyncList<string[]>(loader, [], [], { cacheKey: 'k2' }));
    await waitFor(() => expect(first.result.current.data).toEqual(['ok']));
    cleanup();

    const second = renderHook(() => useAsyncList<string[]>(loader, [], [], { cacheKey: 'k2' }));
    await waitFor(() => expect(second.result.current.loading).toBe(false));
    expect(second.result.current.data).toEqual(['ok']); // stale kept
    expect(second.result.current.error).toBeNull();
  });

  test('distinct cacheKeys do not collide (debrief vs debrief-insights regression)', async () => {
    const a = renderHook(() => useAsyncList(async () => 'A', [], [], { cacheKey: 'debrief:r1' }));
    await waitFor(() => expect(a.result.current.data).toBe('A'));
    cleanup();
    const b = renderHook(() =>
      useAsyncList(async () => 'B', [], [], { cacheKey: 'debrief-insights:r1' }),
    );
    expect(b.result.current.data).toBeNull(); // different key -> no cross-serve
    await waitFor(() => expect(b.result.current.data).toBe('B'));
  });

  test('no cacheKey => never caches (cold every mount)', async () => {
    const first = renderHook(() => useAsyncList(async () => 'X', []));
    await waitFor(() => expect(first.result.current.data).toBe('X'));
    cleanup();
    const second = renderHook(() => useAsyncList(async () => 'X', []));
    expect(second.result.current.data).toBeNull(); // no cache, cold
  });

  test('clearAsyncCache empties the cache', async () => {
    const h = renderHook(() => useAsyncList(async () => 'Y', [], [], { cacheKey: 'k3' }));
    await waitFor(() => expect(h.result.current.data).toBe('Y'));
    expect(__asyncCache.has('k3')).toBe(true);
    clearAsyncCache();
    expect(__asyncCache.has('k3')).toBe(false);
  });
});
