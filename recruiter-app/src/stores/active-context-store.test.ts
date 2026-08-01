import { beforeEach, describe, expect, test } from 'bun:test';
import { useActiveContextStore } from './active-context-store';

beforeEach(() => {
  useActiveContextStore.getState().clear();
});

describe('active context store', () => {
  test('defaults to null fields', () => {
    const s = useActiveContextStore.getState();
    expect(s.requisitionId).toBeNull();
    expect(s.roleTitle).toBeNull();
    expect(s.source).toBeNull();
  });

  test('setContext populates fields', () => {
    useActiveContextStore
      .getState()
      .setContext({ requisitionId: 'req-1', roleTitle: 'Staff PM', source: 'intake' });
    const s = useActiveContextStore.getState();
    expect(s.requisitionId).toBe('req-1');
    expect(s.roleTitle).toBe('Staff PM');
    expect(s.source).toBe('intake');
  });

  test('clear resets all fields', () => {
    useActiveContextStore
      .getState()
      .setContext({ requisitionId: 'x', roleTitle: 'Y', source: 'roles' });
    useActiveContextStore.getState().clear();
    const s = useActiveContextStore.getState();
    expect(s.requisitionId).toBeNull();
    expect(s.roleTitle).toBeNull();
    expect(s.source).toBeNull();
  });
});
