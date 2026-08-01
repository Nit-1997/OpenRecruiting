import { beforeEach, describe, expect, test } from 'bun:test';
import { REQS } from '@/fixtures/roles';
import { useRoleStore } from './role-store';

describe('useRoleStore', () => {
  beforeEach(() => {
    localStorage.clear();
    useRoleStore.getState().reset();
  });

  test('initial roles include all fixture roles', () => {
    const { roles } = useRoleStore.getState();
    expect(roles.length).toBe(REQS.length);
  });

  test('addRole prepends a new role (newest first)', () => {
    useRoleStore.getState().addRole({
      id: 'new-1',
      title: 'Test role',
      loc: 'SF · Eng',
      pipeline: 'Draft',
      status: 'draft',
      dept: 'Engineering',
      owner: 'Nitin',
      created_at: new Date().toISOString(),
      ready_to_debrief: false,
      must_have: [],
      nice_to_have: [],
    });
    const { roles } = useRoleStore.getState();
    expect(roles.length).toBe(REQS.length + 1);
    expect(roles[0]?.id).toBe('new-1');
    expect(roles.find((r) => r.id === 'new-1')?.status).toBe('draft');
  });

  test('addRole upserts on id collision (replaces existing role)', () => {
    const baseRole = {
      id: 'same-id',
      title: 'First draft',
      loc: 'SF · Eng',
      pipeline: 'Draft',
      status: 'draft' as const,
      dept: 'Engineering',
      owner: 'Nitin',
      created_at: new Date().toISOString(),
      ready_to_debrief: false,
      must_have: [],
      nice_to_have: [],
    };
    useRoleStore.getState().addRole(baseRole);
    useRoleStore.getState().addRole({ ...baseRole, title: 'Second draft', status: 'live' });
    const { roles } = useRoleStore.getState();
    expect(roles.filter((r) => r.id === 'same-id').length).toBe(1);
    const found = roles.find((r) => r.id === 'same-id');
    expect(found?.title).toBe('Second draft');
    expect(found?.status).toBe('live');
  });

  test('persists under key openrecruiting.roles.v1', () => {
    useRoleStore.getState().addRole({
      id: 'persist-1',
      title: 'Persist',
      loc: 'SF · Eng',
      pipeline: 'Draft',
      status: 'draft',
      dept: 'Engineering',
      owner: 'Nitin',
      created_at: new Date().toISOString(),
      ready_to_debrief: false,
      must_have: [],
      nice_to_have: [],
    });
    const raw = localStorage.getItem('openrecruiting.roles.v1');
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw ?? '{}');
    expect(parsed.state.roles.find((r: { id: string }) => r.id === 'persist-1')).toBeTruthy();
  });

  test('updateRole replaces existing role by id', () => {
    useRoleStore.getState().addRole({
      id: 'new-2',
      title: 'Initial',
      loc: 'SF · Eng',
      pipeline: 'Draft',
      status: 'draft',
      dept: 'Engineering',
      owner: 'Nitin',
      created_at: new Date().toISOString(),
      ready_to_debrief: false,
      must_have: [],
      nice_to_have: [],
    });
    useRoleStore.getState().updateRole('new-2', { status: 'live', title: 'Published' });
    const role = useRoleStore.getState().roles.find((r) => r.id === 'new-2');
    expect(role?.status).toBe('live');
    expect(role?.title).toBe('Published');
  });

  test('removeRole removes a role by id', () => {
    const [firstRole] = REQS;
    if (!firstRole) throw new Error('REQS fixture must not be empty');
    useRoleStore.getState().removeRole(firstRole.id);
    const { roles } = useRoleStore.getState();
    expect(roles.find((r) => r.id === firstRole.id)).toBeUndefined();
  });
});
