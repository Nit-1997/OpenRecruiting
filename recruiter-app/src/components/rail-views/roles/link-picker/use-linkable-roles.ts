'use client';

import { useMemo } from 'react';
import { useRequisitions } from '@/hooks/use-services';
import type { RoleListItem } from '@/services/requisitions';
import { selectLinkableRoles } from './select-linkable-roles';

// One full page of roles, fetched with NO server `q`: all filtering, search,
// and fuzzy ranking happen client-side so search is instant and the
// meeting-title ranking can see every role at once. 100 is the backend's max
// page_size — orgs above that would need real pagination (see picker note).
const PICKER_PAGE_SIZE = 100;

export interface UseLinkableRolesResult {
  roles: RoleListItem[];
  loading: boolean;
  error: Error | null;
}

/**
 * The picker's role list: every linkable role, ordered by `searchQuery` when
 * the user is typing, else by fuzzy match to `meetingTitle`. Data-fetching
 * lives here; the ordering/filtering logic is the pure `selectLinkableRoles`.
 */
export function useLinkableRoles(
  meetingTitle: string,
  searchQuery: string,
): UseLinkableRolesResult {
  const page = useRequisitions(undefined, { page: 1, page_size: PICKER_PAGE_SIZE });
  const roles = useMemo(
    () => selectLinkableRoles(page.data?.items ?? [], { meetingTitle, searchQuery }),
    [page.data?.items, meetingTitle, searchQuery],
  );
  return { roles, loading: page.loading, error: page.error };
}
