'use client';

import { Search } from 'lucide-react';
import { useEffect, useRef } from 'react';
import type { RequisitionStatus } from '@/domain';
import type { RoleListItem } from '@/services/requisitions';

// planned/intake_pending/closed → the short badge the rail already uses.
const STATUS_LABEL: Record<RequisitionStatus, string> = {
  draft: 'draft',
  planned: 'open',
  intake_pending: 'pending',
  closed: 'closed',
};

const CREATED_DATE_FMT = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
});

function formatCreated(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '' : CREATED_DATE_FMT.format(date);
}

function countLabel(count: number, singular: string): string {
  return `${count} ${count === 1 ? singular : `${singular}s`}`;
}

/**
 * Step 1 of the Link-to-Existing picker: search + the ranked, metadata-rich
 * list of linkable roles. Presentational only — the caller owns the data
 * (via useLinkableRoles) and the query state.
 */
export function RolePickStep({
  id,
  roles,
  query,
  loading,
  onQuery,
  onPick,
}: {
  id: string;
  roles: RoleListItem[];
  query: string;
  loading: boolean;
  onQuery: (q: string) => void;
  onPick: (reqId: string) => void;
}) {
  // Focus the search on open (a11y-clean alternative to the autoFocus attr).
  const searchRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    searchRef.current?.focus();
  }, []);

  return (
    <>
      <div className="mb-3 flex items-center rounded-[10px] border border-border bg-white px-3 py-2 focus-within:border-text-primary">
        <Search strokeWidth={1.75} className="mr-2 h-3.5 w-3.5 text-text-muted" />
        <input
          ref={searchRef}
          id={`${id}-search`}
          type="text"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder="Search by role, team, or location…"
          className="min-w-0 flex-1 border-0 bg-transparent text-[13px] text-text-primary placeholder:text-text-muted focus:outline-none"
        />
      </div>

      {roles.length === 0 ? (
        <p
          id={`${id}-empty`}
          className="rounded-[10px] border border-border border-dashed bg-surface/40 px-3 py-6 text-center text-[12.5px] text-text-muted"
        >
          {loading
            ? 'Loading roles…'
            : query.trim()
              ? `No roles match “${query.trim()}”.`
              : 'No roles with active rounds to link into.'}
        </p>
      ) : (
        <ul id={`${id}-list`} className="flex max-h-72 flex-col gap-1 overflow-y-auto">
          {roles.map((role) => (
            <li key={role.id}>
              <button
                id={`${id}-pick-${role.id}`}
                type="button"
                onClick={() => onPick(role.id)}
                className="flex w-full items-start justify-between gap-3 rounded-[10px] border border-transparent px-3 py-2 text-left transition-colors hover:border-border hover:bg-surface/60"
              >
                <span className="min-w-0">
                  <span className="block truncate text-[13px] text-text-primary">
                    {role.role_title}
                  </span>
                  <span className="mt-0.5 block truncate text-[11.5px] text-text-muted">
                    {role.department} · {role.role_location || '—'}
                  </span>
                  <span
                    id={`${id}-meta-${role.id}`}
                    className="mt-0.5 block truncate text-[11px] text-text-faint"
                  >
                    {countLabel(role.pipeline.candidate_count, 'candidate')} ·{' '}
                    {countLabel(role.pipeline.round_count, 'round')} · Created{' '}
                    {formatCreated(role.created_at)}
                  </span>
                </span>
                <span className="shrink-0 font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
                  {STATUS_LABEL[role.status]}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
