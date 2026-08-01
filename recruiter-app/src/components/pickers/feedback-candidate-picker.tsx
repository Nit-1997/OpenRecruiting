'use client';

import { ChevronLeft, ChevronRight, Search, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import {
  type CandidateFixture,
  type CandidateStatus,
  getCandidatesForReq,
} from '@/fixtures/candidates';
import { candidatesForRolePackets } from '@/fixtures/feedback-packets';
import { cn, pickAvatarFg } from '@/lib/utils';
type FeedbackFilter = 'all' | CandidateStatus;

interface FeedbackCandidatePickerProps {
  id: string;
  reqId: string;
  roleTitle?: string;
  onPick: (candidate: CandidateFixture) => void;
  onCancel: () => void;
  pageSize?: number;
}

export function FeedbackCandidatePicker({
  id,
  reqId,
  roleTitle,
  onPick,
  onCancel,
  pageSize = 5,
}: FeedbackCandidatePickerProps) {
  const packetCandidateIds = candidatesForRolePackets(reqId);
  const list: CandidateFixture[] = useMemo(() => {
    const full = getCandidatesForReq(reqId);
    if (packetCandidateIds.length === 0) return full;
    const allowed = new Set(packetCandidateIds);
    const prioritized = full.filter((c) => allowed.has(c.id));
    const rest = full.filter((c) => !allowed.has(c.id));
    return [...prioritized, ...rest];
  }, [reqId, packetCandidateIds]);

  const [q, setQ] = useState('');
  const [filter, setFilter] = useState<FeedbackFilter>('all');
  const [page, setPage] = useState(0);

  const filterTabs: { id: FeedbackFilter; label: string; count: number }[] = [
    { id: 'all', label: 'All', count: list.length },
    {
      id: 'ready',
      label: 'Ready',
      count: list.filter((c) => c.status === 'ready').length,
    },
    {
      id: 'waiting',
      label: 'Awaiting',
      count: list.filter((c) => c.status === 'waiting').length,
    },
    {
      id: 'early',
      label: 'Early',
      count: list.filter((c) => c.status === 'early').length,
    },
  ];

  const filtered = useMemo(() => {
    const qn = q.trim().toLowerCase();
    return list.filter((c) => {
      if (filter !== 'all' && c.status !== filter) return false;
      if (!qn) return true;
      return `${c.name} ${c.stage} ${c.flag}`.toLowerCase().includes(qn);
    });
  }, [list, q, filter]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, totalPages - 1);
  const slice = filtered.slice(safePage * pageSize, safePage * pageSize + pageSize);

  useEffect(() => {
    setPage(0);
  }, []);

  return (
    <div id={id} className="max-w-[760px]">
      <div id={`${id}-head`} className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div id={`${id}-title-wrap`}>
          <div
            id={`${id}-eyebrow`}
            className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]"
          >
            Packet · pick a candidate
          </div>
          {roleTitle && (
            <h3
              id={`${id}-title`}
              className="mt-1 font-display text-[26px] text-text-primary leading-tight tracking-[-0.01em]"
            >
              {roleTitle}
            </h3>
          )}
        </div>
        <div
          id={`${id}-meta`}
          className="font-mono text-[11px] text-text-muted uppercase tracking-[0.1em]"
        >
          {list.length} in pipeline
        </div>
      </div>

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
            placeholder="Search candidates by name, stage, or signal..."
            className="min-w-0 flex-1 border-0 bg-transparent text-[13px] text-text-primary placeholder:text-text-muted focus:outline-none"
            aria-label="Search candidates"
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

      {slice.length === 0 ? (
        <div
          id={`${id}-empty`}
          className="rounded-[14px] border border-border border-dashed bg-white px-5 py-10 text-center text-[13px] text-text-muted"
        >
          No candidates match - try a different search or tab.
        </div>
      ) : (
        <div id={`${id}-list`} className="flex flex-col gap-2">
          {slice.map((c) => {
            const hasPacket = packetCandidateIds.includes(c.id);
            return (
              <button
                key={c.id}
                id={`${id}-card-${c.id}`}
                type="button"
                onClick={() => onPick(c)}
                className={cn(
                  'grid grid-cols-[36px_minmax(0,1fr)_minmax(160px,auto)_16px] items-center gap-3 rounded-[12px] border bg-white px-3.5 py-3 text-left transition-colors',
                  'border-border hover:border-text-primary',
                )}
              >
                <span
                  id={`${id}-card-${c.id}-avatar`}
                  aria-hidden
                  className="flex h-9 w-9 items-center justify-center rounded-full font-mono text-[11px]"
                  style={{ background: c.color, color: pickAvatarFg(c.color) }}
                >
                  {c.avatar}
                </span>
                <span id={`${id}-card-${c.id}-body`} className="min-w-0">
                  <span
                    id={`${id}-card-${c.id}-name`}
                    className="block truncate font-medium font-sans text-[14px] text-text-primary"
                  >
                    {c.name}
                  </span>
                  <span
                    id={`${id}-card-${c.id}-stage`}
                    className="mt-0.5 block truncate text-[12px] text-text-muted"
                  >
                    {c.role} {c.role !== '' ? '·' : ''} {c.stage}
                  </span>
                </span>
                <span
                  id={`${id}-card-${c.id}-flag`}
                  className="text-right font-mono text-[11px] text-text-secondary"
                >
                  <span id={`${id}-card-${c.id}-flag-top`} className="block text-text-primary">
                    {c.flag}
                  </span>
                  <span id={`${id}-card-${c.id}-flag-bot`} className="mt-0.5 block text-text-muted">
                    {hasPacket ? 'Packet ready' : `${c.scoresIn}/${c.rounds} scorecards in`}
                  </span>
                </span>
                <ChevronRight
                  id={`${id}-card-${c.id}-chev`}
                  strokeWidth={1.75}
                  className="h-4 w-4 text-text-muted"
                  aria-hidden
                />
              </button>
            );
          })}
        </div>
      )}

      {totalPages > 1 && (
        <div
          id={`${id}-pager`}
          className="mt-4 flex items-center justify-between font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]"
        >
          <span id={`${id}-pager-meta`}>
            Showing {safePage * pageSize + 1}-{Math.min(filtered.length, (safePage + 1) * pageSize)}{' '}
            of {filtered.length}
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

      <div
        id={`${id}-footer`}
        className="mt-5 flex flex-wrap items-center justify-between gap-4 border-border border-t pt-4"
      >
        <div
          id={`${id}-hint`}
          className="max-w-[420px] text-[12.5px] text-text-muted leading-[1.5]"
        >
          Pick a candidate and I will pull their full panel feedback rollup. Or type a name like{' '}
          <b className="font-medium text-text-primary">&quot;packet for Priya&quot;</b> in the
          composer.
        </div>
        <div id={`${id}-actions`} className="flex items-center gap-2">
          <button
            id={`${id}-cancel`}
            type="button"
            onClick={onCancel}
            className="inline-flex items-center rounded-full border border-border bg-white px-3.5 py-2 font-medium font-sans text-[13px] text-text-primary transition-colors hover:border-text-primary"
          >
            Back
          </button>
        </div>
      </div>
    </div>
  );
}
