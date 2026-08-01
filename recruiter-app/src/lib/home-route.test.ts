import { beforeEach, describe, expect, mock, test } from 'bun:test';
import { useSessionStore } from '@/stores';
import { routeChip } from './home-route';

describe('routeChip', () => {
  beforeEach(() => {
    useSessionStore.getState().reset();
  });

  test('a path value pushes that path and starts no sub-agent session', () => {
    const push = mock((_: string) => {});
    routeChip({ push }, '/view/roles');
    expect(push).toHaveBeenCalledWith('/view/roles');
    expect(useSessionStore.getState().sessions.intake).toBeFalsy();
  });

  test('a sub-agent value seeds the session and pushes /<tab>', () => {
    const push = mock((_: string) => {});
    routeChip({ push }, 'intake');
    expect(push).toHaveBeenCalledWith('/intake');
    expect(useSessionStore.getState().sessions.intake).toBeTruthy();
  });
});
