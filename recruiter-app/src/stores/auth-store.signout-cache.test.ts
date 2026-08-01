import { afterEach, describe, expect, test } from 'bun:test';
import { __asyncCache, clearAsyncCache } from '@/hooks/use-services';
import { useAuthStore } from './auth-store';

afterEach(() => clearAsyncCache());

describe('signOut cache reset', () => {
  test('signOut empties the async cache', async () => {
    __asyncCache.set('role:abc', { data: { id: 'abc' } });
    expect(__asyncCache.size).toBeGreaterThan(0);
    await useAuthStore.getState().signOut();
    expect(__asyncCache.size).toBe(0);
  });
});
