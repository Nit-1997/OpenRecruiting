import { beforeEach, describe, expect, test } from 'bun:test';
import type { RoleFixture } from '@/fixtures/roles';
import { useArtifactStore, useSessionStore } from '@/stores';
import {
  pickMode,
  pickRoleForSourcing,
  resetSourcing,
  type SourcingSelections,
  submitQuery,
} from './flow';

const DEMO_ROLE: RoleFixture = {
  id: 'pm-sfo',
  title: 'Staff PM · Sunnyvale',
  loc: 'Full-time · Product',
  pipeline: '4 candidates awaiting decision',
  status: 'live',
  dept: 'Product',
  owner: 'Taylor',
  created_at: '2026-03-22T14:30:00Z',
  ready_to_debrief: true,
  must_have: ['Product strategy', 'Stakeholder mgmt', 'Metrics'],
  nice_to_have: [],
};

function selections(): SourcingSelections {
  return (useSessionStore.getState().sessions.sourcing?.selections ?? {}) as SourcingSelections;
}

beforeEach(() => {
  useSessionStore.getState().reset();
  useArtifactStore.getState().reset();
  if (typeof localStorage !== 'undefined') localStorage.clear();
});

describe('sourcing flow', () => {
  test('pickMode(existing) advances to role_pick', async () => {
    useSessionStore.getState().startSession('sourcing', 'mode_pick');
    await pickMode('existing');
    const session = useSessionStore.getState().sessions.sourcing;
    expect(session?.stage).toBe('role_pick');
    expect(selections().mode).toBe('existing');
  });

  test('pickMode(fresh) advances to query_build', async () => {
    useSessionStore.getState().startSession('sourcing', 'mode_pick');
    await pickMode('fresh');
    const session = useSessionStore.getState().sessions.sourcing;
    expect(session?.stage).toBe('query_build');
  });

  test('pickRoleForSourcing moves to preferences_chat with role bound', async () => {
    useSessionStore.getState().startSession('sourcing', 'role_pick');
    await pickRoleForSourcing(DEMO_ROLE);
    const session = useSessionStore.getState().sessions.sourcing;
    expect(session?.stage).toBe('preferences_chat');
    const s = selections();
    expect(s.roleId).toBe('pm-sfo');
    expect(s.roleTitle).toBe('Staff PM · Sunnyvale');
    expect(s.mode).toBe('existing');
    expect(s.preferenceTurnIdx).toBeDefined();
  });

  test('submitQuery seeds the query as the first preference and enters preferences_chat', async () => {
    useSessionStore.getState().startSession('sourcing', 'query_build');
    const query = 'Staff PMs in Sunnyvale with 7 years of growth experience';
    await submitQuery(query);
    const session = useSessionStore.getState().sessions.sourcing;
    expect(session?.stage).toBe('preferences_chat');
    const s = selections();
    expect(s.mode).toBe('fresh');
    expect(s.roleId).toBeUndefined();
    expect(s.queryText).toBe(query);
    expect(s.preferenceAnswers?.[0]).toBe(query);
  });

  test('resetSourcing clears session', async () => {
    useSessionStore.getState().startSession('sourcing', 'query_build');
    await submitQuery('Staff PMs with 7 years of experience');
    resetSourcing();
    expect(useSessionStore.getState().sessions.sourcing).toBeNull();
  });
});
