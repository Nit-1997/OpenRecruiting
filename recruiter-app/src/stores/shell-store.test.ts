import { beforeEach, describe, expect, test } from 'bun:test';
import { useShellStore } from './shell-store';

beforeEach(() => {
  useShellStore.getState().reset();
});

describe('shell-store', () => {
  test('initial state is home', () => {
    const s = useShellStore.getState();
    expect(s.activeTabId).toBeNull();
    expect(s.activeRailId).toBeNull();
    expect(s.mode()).toBe('home');
  });

  test('setActiveTab clears rail and sets tab', () => {
    useShellStore.getState().setActiveRail('roles');
    useShellStore.getState().setActiveTab('intake');
    expect(useShellStore.getState().activeTabId).toBe('intake');
    expect(useShellStore.getState().activeRailId).toBeNull();
  });

  test('setActiveRail stashes active tab', () => {
    useShellStore.getState().setActiveTab('debrief');
    useShellStore.getState().setActiveRail('roles');
    const s = useShellStore.getState();
    expect(s.activeTabId).toBeNull();
    expect(s.activeRailId).toBe('roles');
    expect(s.stashed).toBe('debrief');
  });

  test('closeRail restores stashed tab', () => {
    useShellStore.getState().setActiveTab('debrief');
    useShellStore.getState().setActiveRail('roles');
    useShellStore.getState().closeRail();
    const s = useShellStore.getState();
    expect(s.activeRailId).toBeNull();
    expect(s.activeTabId).toBe('debrief');
    expect(s.stashed).toBeNull();
  });

  test('mode derivation: qna when rail active', () => {
    useShellStore.getState().setActiveRail('roles');
    expect(useShellStore.getState().mode()).toBe('qna');
  });

  test('mode derivation: agentic when tab active', () => {
    useShellStore.getState().setActiveTab('intake');
    expect(useShellStore.getState().mode()).toBe('agentic');
  });

  test('goHome clears everything', () => {
    useShellStore.getState().setActiveTab('intake');
    useShellStore.getState().setActiveRail('roles');
    useShellStore.getState().goHome();
    const s = useShellStore.getState();
    expect(s.activeTabId).toBeNull();
    expect(s.activeRailId).toBeNull();
    expect(s.stashed).toBeNull();
  });

  test('setRailDetail requires rail active', () => {
    useShellStore.getState().setActiveRail('roles');
    useShellStore.getState().setRailDetail({ viewId: 'roles', detailId: 'pm-sfo' });
    expect(useShellStore.getState().railDetail?.detailId).toBe('pm-sfo');
  });
});
