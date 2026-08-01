'use client';

import { ChevronLeft, ChevronRight, Search, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { REQS, type RoleFixture } from '@/fixtures/roles';
import { cn } from '@/lib/utils';

type ReqFilter = 'all' | 'live' | 'paused' | 'draft' | 'mine';

interface ReqPickGridProps {
  id: string;
  onPick: (role: RoleFixture) => void;
  pageSize?: number;
  ownedBy?: string;
  /**
   * Data source for the grid. When omitted, falls back to the `REQS` fixture
   * (mock-path + the sourcing sub-agent, which both still drive off fixtures).
   * The debrief flow passes real, fetched roles here so the grid renders live
   * backend data with zero changes to its render logic.
   */
  roles?: RoleFixture[];
}

export function ReqPickGrid({
  id,
  onPick,
  pageSize = 6,
  ownedBy = 'Nitin',
  roles,
}: ReqPickGridProps) {
  const source = roles ?? REQS;
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState<ReqFilter>('all');
  const [page, setPage] = useState(0);

  const counts = useMemo(() => {
    const mine = source.filter((r) => r.owner === ownedBy).length;
    return {
      all: source.length,
      live: source.filter((r) => r.status === 'live').length,
      paused: source.filter((r) => r.status === 'paused').length,
      draft: source.filter((r) => r.status === 'draft').length,
      mine,
    };
  }, [ownedBy, source]);

  const filterTabs: { id: ReqFilter; label: string; count: number }[] = [
    { id: 'all', label: 'All', count: counts.all },
    { id: 'live', label: 'Live', count: counts.live },
    { id: 'paused', label: 'Paused', count: counts.paused },
    { id: 'draft', label: 'Drafts', count: counts.draft },
    { id: 'mine', label: 'Owned by me', count: counts.mine },
  ];

  const filtered = useMemo(() => {
    const qn = q.trim().toLowerCase();
    return source.filter((r) => {
      if (filter === 'mine' && r.owner !== ownedBy) return false;
      if (filter !== 'all' && filter !== 'mine' && r.status !== filter) return false;
      if (!qn) return true;
      return (
        r.title.toLowerCase().includes(qn) ||
        r.loc.toLowerCase().includes(qn) ||
        r.dept.toLowerCase().includes(qn)
      );
    });
  }, [q, filter, ownedBy, source]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, totalPages - 1);
  const slice = filtered.slice(safePage * pageSize, safePage * pageSize + pageSize);

  useEffect(() => {
    setPage(0);
  }, []);

  return (
    <div id={id} className="max-w-[760px]">
      <div id={`${id}-bar`} className="mb-4 flex flex-col gap-3">
        <div
          id={`${id}-search`}
          className="relative flex items-center rounded-full border border-border bg-white px-3 py-2 transition-colors focus-within:border-text-primary"
        >
          <Search strokeWidth={1.75} className="mr-2 h-3.5 w-3.5 text-text-muted" aria-hidden />
          <input
            id={`${id}-search-input`}
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter roles by title, team, or location…"
            className="min-w-0 flex-1 border-0 bg-transparent text-[13px] text-text-primary placeholder:text-text-muted focus:outline-none"
            aria-label="Search roles"
          />
          {q && (
            <button
              id={`${id}-search-clear`}
              type="button"
              aria-label="Clear search"
              onClick={() => setQ('')}
              className="flex h-5 w-5 items-center justify-center rounded-full text-text-muted hover:text-text-primary"
            >
              <X strokeWidth={1.75} className="h-3 w-3" />
            </button>
          )}
        </div>
        <div id={`${id}-tabs`} className="flex flex-wrap gap-1.5">
          {filterTabs.map((t) => {
            const active = filter === t.id;
            return (
              <button
                key={t.id}
                id={`${id}-tab-${t.id}`}
                type="button"
                onClick={() => setFilter(t.id)}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 font-sans text-[12px] transition-colors',
                  active
                    ? 'border-text-primary bg-text-primary text-white'
                    : 'border-border bg-white text-text-muted hover:border-text-primary hover:text-text-primary',
                )}
              >
                <span>{t.label}</span>
                <span
                  id={`${id}-tab-${t.id}-count`}
                  className={cn(
                    'rounded-full px-1.5 font-mono text-[10px]',
                    active ? 'bg-white/20 text-white' : 'bg-surface text-text-faint',
                  )}
                >
                  {t.count}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {filtered.length === 0 ? (
        <div
          id={`${id}-empty`}
          className="rounded-[14px] border border-border border-dashed bg-white px-5 py-10 text-center text-[13px] text-text-muted"
        >
          No roles match &quot;{q}&quot;. Try a team name, location, or clear the filter.
        </div>
      ) : (
        <div id={`${id}-grid`} className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
          {slice.map((r) => (
            <button
              key={r.id}
              id={`${id}-card-${r.id}`}
              type="button"
              onClick={() => onPick(r)}
              className="group flex flex-col gap-1.5 rounded-[14px] border border-border bg-white px-4 py-3.5 text-left transition-colors hover:border-text-primary"
            >
              <h4
                id={`${id}-card-${r.id}-title`}
                className="font-medium font-sans text-[14px] text-text-primary leading-tight"
              >
                {r.title}
              </h4>
              <div id={`${id}-card-${r.id}-loc`} className="text-[12px] text-text-muted">
                {r.loc}
              </div>
              <div
                id={`${id}-card-${r.id}-pipeline`}
                className="mt-1 flex items-center gap-2 font-mono text-[10.5px] text-text-secondary uppercase tracking-[0.08em]"
              >
                <span
                  id={`${id}-card-${r.id}-dot`}
                  aria-hidden
                  className={cn(
                    'h-1.5 w-1.5 rounded-full',
                    r.status === 'live'
                      ? 'bg-[#10B981]'
                      : r.status === 'paused'
                        ? 'bg-[#F59E0B]'
                        : 'bg-text-muted',
                  )}
                />
                {r.pipeline}
              </div>
            </button>
          ))}
        </div>
      )}

      {totalPages > 1 && (
        <div
          id={`${id}-pager`}
          className="mt-4 flex items-center justify-between font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]"
        >
          <span id={`${id}-pager-meta`}>
            {safePage * pageSize + 1}–{Math.min((safePage + 1) * pageSize, filtered.length)} of{' '}
            {filtered.length}
          </span>
          <div id={`${id}-pager-ctrls`} className="flex items-center gap-1.5">
            <button
              id={`${id}-pager-prev`}
              type="button"
              aria-label="Previous page"
              disabled={safePage === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              className="flex h-7 w-7 items-center justify-center rounded-full border border-border bg-white text-text-muted transition-colors hover:border-text-primary hover:text-text-primary disabled:opacity-40"
            >
              <ChevronLeft strokeWidth={1.75} className="h-3.5 w-3.5" />
            </button>
            {Array.from({ length: totalPages }).map((_, i) => (
              <button
                // biome-ignore lint/suspicious/noArrayIndexKey: page numbers are stable indices
                key={i}
                id={`${id}-pager-dot-${i}`}
                type="button"
                onClick={() => setPage(i)}
                className={cn(
                  'flex h-7 min-w-7 items-center justify-center rounded-full border px-2 font-mono text-[11px] transition-colors',
                  i === safePage
                    ? 'border-text-primary bg-text-primary text-white'
                    : 'border-border bg-white text-text-muted hover:border-text-primary hover:text-text-primary',
                )}
              >
                {i + 1}
              </button>
            ))}
            <button
              id={`${id}-pager-next`}
              type="button"
              aria-label="Next page"
              disabled={safePage >= totalPages - 1}
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              className="flex h-7 w-7 items-center justify-center rounded-full border border-border bg-white text-text-muted transition-colors hover:border-text-primary hover:text-text-primary disabled:opacity-40"
            >
              <ChevronRight strokeWidth={1.75} className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
