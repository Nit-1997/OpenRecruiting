import { afterEach, describe, expect, test } from 'bun:test';
import { useIntakeStore } from './intake-store';

afterEach(() => {
  useIntakeStore.getState().reset();
});

describe('useIntakeStore', () => {
  test('initial state', () => {
    const s = useIntakeStore.getState();
    expect(s.sessionId).toBeNull();
    expect(s.pendingTransition).toBeNull();
    expect(s.error).toBeNull();
  });

  test('setSessionId updates and clears prior pendingTransition + error', () => {
    useIntakeStore.getState().setPendingTransition('prefilling', 3000);
    useIntakeStore.getState().setError('boom');
    useIntakeStore.getState().setSessionId('sess-1');
    const s = useIntakeStore.getState();
    expect(s.sessionId).toBe('sess-1');
    expect(s.pendingTransition).toBeNull();
    expect(s.error).toBeNull();
  });

  test('setPendingTransition stores stage + expiresAt', () => {
    const before = Date.now();
    useIntakeStore.getState().setPendingTransition('prefilling', 3000);
    const s = useIntakeStore.getState();
    expect(s.pendingTransition?.to).toBe('prefilling');
    expect(s.pendingTransition?.expiresAt).toBeGreaterThanOrEqual(before + 3000);
  });

  test('clearPendingTransition resets to null', () => {
    useIntakeStore.getState().setPendingTransition('prefilling', 3000);
    useIntakeStore.getState().clearPendingTransition();
    expect(useIntakeStore.getState().pendingTransition).toBeNull();
  });

  test('setError + clearError', () => {
    useIntakeStore.getState().setError('boom');
    expect(useIntakeStore.getState().error).toBe('boom');
    useIntakeStore.getState().clearError();
    expect(useIntakeStore.getState().error).toBeNull();
  });

  test('reset wipes every field', () => {
    useIntakeStore.getState().setSessionId('s');
    useIntakeStore.getState().setPendingTransition('prefilling', 1000);
    useIntakeStore.getState().setError('e');
    useIntakeStore.getState().reset();
    const s = useIntakeStore.getState();
    expect(s.sessionId).toBeNull();
    expect(s.pendingTransition).toBeNull();
    expect(s.error).toBeNull();
  });
});
