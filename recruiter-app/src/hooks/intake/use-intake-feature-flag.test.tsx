import { afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { renderHook, waitFor } from '@testing-library/react';

const fetchFlagMock = mock(async () => ({ intake_v2_enabled: true }));

// Spread `...actual` so we only override `fetchIntakeFeatureFlag`. A full
// replacement of `@/lib/intake/api` is process-wide in bun and DECOUPLES the
// module's internal bindings (e.g. the `IntakeApiError` class that the real
// functions `throw`), which corrupts the genuine api.*.test.ts suites that run
// in the same process. Keeping the real exports avoids that cross-file damage.
mock.module('@/lib/intake/api', () => {
  const actual = require('@/lib/intake/api');
  return { ...actual, fetchIntakeFeatureFlag: fetchFlagMock };
});

beforeEach(() => {
  fetchFlagMock.mockClear();
});

afterEach(() => {
  fetchFlagMock.mockReset();
});

describe('useIntakeFeatureFlag', () => {
  test('returns enabled=true when backend says so', async () => {
    fetchFlagMock.mockImplementation(async () => ({ intake_v2_enabled: true }));
    const { useIntakeFeatureFlag } = await import('./use-intake-feature-flag');
    const { result } = renderHook(() => useIntakeFeatureFlag());
    expect(result.current.isLoading).toBe(true);
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.enabled).toBe(true);
  });

  test('returns enabled=false on 403/feature_disabled', async () => {
    fetchFlagMock.mockImplementation(async () => {
      throw Object.assign(new Error('disabled'), {
        name: 'IntakeApiError',
        status: 403,
        code: 'feature_disabled',
      });
    });
    const { useIntakeFeatureFlag } = await import('./use-intake-feature-flag');
    const { result } = renderHook(() => useIntakeFeatureFlag());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.enabled).toBe(false);
  });

  test('returns enabled=false on network error', async () => {
    fetchFlagMock.mockImplementation(async () => {
      throw new Error('network down');
    });
    const { useIntakeFeatureFlag } = await import('./use-intake-feature-flag');
    const { result } = renderHook(() => useIntakeFeatureFlag());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.enabled).toBe(false);
  });

  test('Phase 5 regression: backend 200 with intake_v2_enabled=false hides entry', async () => {
    fetchFlagMock.mockImplementation(async () => ({ intake_v2_enabled: false }));
    const { useIntakeFeatureFlag } = await import('./use-intake-feature-flag');
    const { result } = renderHook(() => useIntakeFeatureFlag());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.enabled).toBe(false);
  });
});
