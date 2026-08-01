// FE-T1: coverage for useShellSync — URL pathname → shell-store reconciliation.
//
// next/navigation is mocked process-wide (test-setup.ts gives usePathname a
// fixed `/`). We re-register it here reading from a mutable `pathnameFixture`
// holder — the SAME non-polluting pattern composer.test.tsx uses — so we can
// drive different routes per render. We restore the fixture to `/` in afterAll
// so the process-wide last-writer-wins mock returns the harmless default for
// any file scheduled after this one.

import { afterAll, afterEach, beforeEach, describe, expect, mock, test } from 'bun:test';
import { cleanup, render } from '@testing-library/react';

let pathnameFixture = '/';

mock.module('next/navigation', () => ({
  useRouter: () => ({
    push: () => {},
    replace: () => {},
    back: () => {},
    forward: () => {},
    refresh: () => {},
    prefetch: () => {},
  }),
  usePathname: () => pathnameFixture,
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));

import { useShellStore } from '@/stores';
import { useShellSync } from './use-shell-sync';

function Harness() {
  useShellSync();
  return <div data-testid="shell-sync-harness" />;
}

function renderAt(path: string) {
  pathnameFixture = path;
  return render(<Harness />);
}

beforeEach(() => {
  useShellStore.getState().reset();
  pathnameFixture = '/';
});

afterEach(() => {
  cleanup();
});

afterAll(() => {
  pathnameFixture = '/';
});

describe('useShellSync - sub-agent routes', () => {
  for (const id of ['intake', 'sourcing', 'debrief', 'brain'] as const) {
    test(`/${id} activates the ${id} tab and clears rail state`, () => {
      // Pre-set a rail so we can prove the tab path clears it.
      useShellStore.getState().setActiveRail('roles');
      renderAt(`/${id}`);

      const s = useShellStore.getState();
      expect(s.activeTabId).toBe(id);
      expect(s.activeRailId).toBeNull();
      expect(s.railDetail).toBeNull();
    });
  }
});

describe('useShellSync - rail (view) routes', () => {
  for (const rail of ['roles', 'integrations'] as const) {
    test(`/view/${rail} activates the ${rail} rail with no detail`, () => {
      renderAt(`/view/${rail}`);

      const s = useShellStore.getState();
      expect(s.activeRailId).toBe(rail);
      expect(s.activeTabId).toBeNull();
      expect(s.railDetail).toBeNull();
    });
  }

  test('/view/roles/req-123 activates the rail AND sets the detail target', () => {
    renderAt('/view/roles/req-123');

    const s = useShellStore.getState();
    expect(s.activeRailId).toBe('roles');
    expect(s.railDetail).toEqual({ viewId: 'roles', detailId: 'req-123' });
  });

  test('switching from a detailed rail to the bare rail clears the stale detail', () => {
    renderAt('/view/roles/req-123');
    expect(useShellStore.getState().railDetail).toEqual({ viewId: 'roles', detailId: 'req-123' });

    cleanup();
    renderAt('/view/roles');
    expect(useShellStore.getState().railDetail).toBeNull();
  });

  test('/view/<unknown-rail> is not a valid rail → falls through to home', () => {
    useShellStore.getState().setActiveTab('intake');
    renderAt('/view/not-a-rail');

    const s = useShellStore.getState();
    expect(s.activeTabId).toBeNull();
    expect(s.activeRailId).toBeNull();
  });
});

describe('useShellSync - home / unrecognized routes', () => {
  test('root path "/" goes home (no tab, no rail)', () => {
    useShellStore.getState().setActiveTab('sourcing');
    renderAt('/');

    const s = useShellStore.getState();
    expect(s.activeTabId).toBeNull();
    expect(s.activeRailId).toBeNull();
    expect(s.railDetail).toBeNull();
  });

  test('an unrecognized first segment goes home', () => {
    useShellStore.getState().setActiveTab('brain');
    renderAt('/settings/profile');

    const s = useShellStore.getState();
    expect(s.activeTabId).toBeNull();
    expect(s.activeRailId).toBeNull();
  });

  test('trailing-slash / empty segments are filtered (// stays home)', () => {
    renderAt('//');
    const s = useShellStore.getState();
    expect(s.activeTabId).toBeNull();
    expect(s.activeRailId).toBeNull();
  });
});
