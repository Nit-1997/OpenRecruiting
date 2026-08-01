import { describe, expect, test } from 'bun:test';
import type { RoleListItem } from '@/services/requisitions';
import { selectLinkableRoles } from './select-linkable-roles';

function role(
  id: string,
  title: string,
  {
    roundCount = 2,
    createdAt = '2026-01-01T00:00:00.000Z',
    location = 'Remote',
    department = 'Engineering',
  }: { roundCount?: number; createdAt?: string; location?: string; department?: string } = {},
): RoleListItem {
  return {
    id,
    role_title: title,
    role_location: location,
    department,
    status: 'planned',
    created_at: createdAt,
    pipeline: { round_count: roundCount, candidate_count: 0 },
  } as unknown as RoleListItem;
}

describe('selectLinkableRoles', () => {
  const roles = [
    role('pm', 'Product Manager'),
    role('fe', 'Senior Frontend Engineer'),
    role('swe', 'Senior Software Engineer'),
    role('noround', 'Empty Role', { roundCount: 0 }),
  ];

  test('drops roles with no active rounds', () => {
    const out = selectLinkableRoles(roles, { meetingTitle: 'x', searchQuery: '' });
    expect(out.map((r) => r.id)).not.toContain('noround');
  });

  test('no query → full linkable list ranked by meeting title', () => {
    const out = selectLinkableRoles(roles, {
      meetingTitle: 'Video Interview with Shipt (Staff AI Engineer)',
      searchQuery: '',
    });
    // Engineer roles outrank Product Manager; PM still present (full list).
    expect(out[0]?.role_title).toContain('Engineer');
    expect(out.at(-1)?.id).toBe('pm');
    expect(out).toHaveLength(3);
  });

  test('query → client-side substring filter on title/department/location', () => {
    const out = selectLinkableRoles(roles, { meetingTitle: 'x', searchQuery: 'frontend' });
    expect(out.map((r) => r.id)).toEqual(['fe']);
  });

  test('query matches location too', () => {
    const remoteOnly = [
      role('a', 'Backend Engineer', { location: 'Remote' }),
      role('b', 'Backend Engineer', { location: 'Bengaluru' }),
    ];
    const out = selectLinkableRoles(remoteOnly, { meetingTitle: 'x', searchQuery: 'bengaluru' });
    expect(out.map((r) => r.id)).toEqual(['b']);
  });

  test('equal fuzzy score falls back to newest-first', () => {
    const sameScore = [
      role('old', 'Data Engineer', { createdAt: '2026-01-01T00:00:00.000Z' }),
      role('new', 'Data Engineer', { createdAt: '2026-06-01T00:00:00.000Z' }),
    ];
    const out = selectLinkableRoles(sameScore, { meetingTitle: 'engineer', searchQuery: '' });
    expect(out.map((r) => r.id)).toEqual(['new', 'old']);
  });
});
