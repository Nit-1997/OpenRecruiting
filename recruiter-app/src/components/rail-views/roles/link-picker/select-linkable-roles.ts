import { rankByFuzzy } from '@/lib/fuzzy-rank';
import type { RoleListItem } from '@/services/requisitions';

export interface SelectLinkableRolesOptions {
  /** The untracked interview's event title, used for default fuzzy ranking. */
  meetingTitle: string;
  /** The picker's search box value. Empty → fuzzy-by-meeting-title order. */
  searchQuery: string;
}

// A role is linkable only if it has at least one active round — the backend
// rejects a link into a round-less role with a 400. The list endpoint already
// excludes the hidden system/untracked template, so round_count is the only
// gate the picker needs to apply.
function isLinkable(role: RoleListItem): boolean {
  return role.pipeline.round_count >= 1;
}

// What the search box and the fuzzy ranker read for each role.
function roleSearchText(role: RoleListItem): string {
  return `${role.role_title} ${role.department} ${role.role_location}`;
}

/**
 * Ordered list of roles for the Link-to-Existing picker.
 *  - keeps only linkable roles (>= 1 active round)
 *  - with a search query: client-side substring filter, ranked by relevance
 *  - without one: the full list ranked by fuzzy match to the meeting title
 *
 * Newest-first is the base order, so equal fuzzy scores keep a stable,
 * predictable sequence. Pure — no React, no I/O.
 */
export function selectLinkableRoles(
  roles: readonly RoleListItem[],
  { meetingTitle, searchQuery }: SelectLinkableRolesOptions,
): RoleListItem[] {
  const linkable = roles
    .filter(isLinkable)
    .slice()
    .sort((a, b) => b.created_at.localeCompare(a.created_at));

  const query = searchQuery.trim();
  if (query) {
    const needle = query.toLowerCase();
    const matches = linkable.filter((role) => roleSearchText(role).toLowerCase().includes(needle));
    return rankByFuzzy(matches, query, roleSearchText);
  }
  return rankByFuzzy(linkable, meetingTitle, (role) => role.role_title);
}
