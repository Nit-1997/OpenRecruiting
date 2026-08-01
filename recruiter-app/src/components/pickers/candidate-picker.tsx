'use client';

import { Check, ChevronLeft, ChevronRight, Lock, Search, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import {
  type CandidateFixture,
  type CandidateStatus,
  getCandidatesForReq,
} from '@/fixtures/candidates';
import { cn, pickAvatarFg } from '@/lib/utils';

type CandidateFilter = 'all' | CandidateStatus | 'selected';

/**
 * A candidate is selectable only when it has real signal (>= 1 completed round
 * WITH feedback) — the backend tags this as `eligibility === 'ready'`. We prefer
 * the canonical backend tier; mock-path fixtures predate it, so fall back to the
 * derived `status` (which the mapper sets to 'ready' for the same tier).
 */
function isReady(c: CandidateFixture): boolean {
  return c.eligibility ? c.eligibility === 'ready' : c.status === 'ready';
}

/** Completed rounds carrying a rating — the parity key. Falls back to completed
 *  rounds (`scoresIn`) for mock-path fixtures that predate `ratedRounds`. */
function ratedCount(c: CandidateFixture): number {
  return c.ratedRounds ?? c.scoresIn;
}

/** Short, human reason a not-ready candidate can't be debriefed yet. */
function notReadyReason(c: CandidateFixture): string {
  const tier = c.eligibility ?? (c.status === 'early' ? 'early_stage' : 'awaiting_signal');
  return tier === 'early_stage' ? 'No completed rounds' : 'No feedback yet';
}

/** "N scorecard(s) · M evidence-backed" for ready candidates with signal. */
function signalLine(c: CandidateFixture): string {
  const fb = c.signal?.feedback_count ?? c.scoresIn;
  const ev = c.signal?.evidence_backed_count ?? 0;
  return `${fb} scorecard${fb === 1 ? '' : 's'} · ${ev} evidence-backed`;
}

interface CandidatePickerProps {
  id: string;
  reqId: string;
  roleTitle?: string;
  selected: string[];
  onToggle: (candidateId: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
  pageSize?: number;
  /**
   * Data source for the picker. When omitted, falls back to the candidate
   * fixture (mock-path). The debrief flow passes real, fetched + mapped
   * candidates here so the picker renders live backend data without changing
   * its render logic.
   */
  candidates?: CandidateFixture[];
}

export function CandidatePicker({
  id,
  reqId,
  roleTitle,
  selected,
  onToggle,
  onConfirm,
  onCancel,
  pageSize = 6,
  candidates,
}: CandidatePickerProps) {
  const list: CandidateFixture[] = candidates ?? getCandidatesForReq(reqId);
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState<CandidateFilter>('all');
  const [page, setPage] = useState(0);

  // Parity gate: a debrief averages each candidate over their rated rounds, so
  // comparing candidates with a DIFFERENT rated-round count is unfair. Once a
  // candidate is selected it fixes the "anchor" count; ready candidates with a
  // different count become non-selectable until the selection clears (mirrors the
  // backend gate). `null` = nothing selected yet → no constraint.
  const anchorCount = useMemo(() => {
    const counts = new Set(list.filter((c) => selected.includes(c.id)).map(ratedCount));
    return counts.size === 1 ? [...counts][0] : null;
  }, [list, selected]);

  const isCompatible = (c: CandidateFixture): boolean =>
    anchorCount === null || selected.includes(c.id) || ratedCount(c) === anchorCount;

  const filterTabs: { id: CandidateFilter; label: string; count: number }[] = [
    { id: 'all', label: 'All', count: list.length },
    {
      id: 'ready',
      label: 'Ready to debrief',
      count: list.filter((c) => c.status === 'ready').length,
    },
    {
      id: 'waiting',
      label: 'Awaiting signal',
      count: list.filter((c) => c.status === 'waiting').length,
    },
    {
      id: 'early',
      label: 'Early stage',
      count: list.filter((c) => c.status === 'early').length,
    },
    { id: 'selected', label: `Selected (${selected.length})`, count: selected.length },
  ];

  const filtered = useMemo(() => {
    const qn = q.trim().toLowerCase();
    const matched = list.filter((c) => {
      if (filter === 'selected' && !selected.includes(c.id)) return false;
      if (filter !== 'all' && filter !== 'selected' && c.status !== filter) return false;
      if (!qn) return true;
      return `${c.name} ${c.stage} ${c.flag}`.toLowerCase().includes(qn);
    });
    // Ready candidates first (selectable + prominent), then the de-emphasized
    // not-ready group. Stable within each group (preserve source order).
    return matched
      .map((c, i) => ({ c, i }))
      .sort((a, b) => {
        const r = Number(isReady(b.c)) - Number(isReady(a.c));
        return r !== 0 ? r : a.i - b.i;
      })
      .map(({ c }) => c);
  }, [list, q, filter, selected]);

  // The confirm gate counts ONLY selected candidates that are ready — a stale
  // not-ready id in `selected` (can't be toggled in via the UI, but defends
  // against an externally-seeded selection) never counts toward the >= 2.
  const readySelectedCount = useMemo(
    () => list.filter((c) => isReady(c) && selected.includes(c.id)).length,
    [list, selected],
  );
  const canConfirm = readySelectedCount >= 2;

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
            Debrief · pick candidates to compare
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
          {list.length} in pipeline · {readySelectedCount} ready selected
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
            placeholder="Search candidates by name, stage, or signal…"
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
          No candidates match — try a different search or tab.
        </div>
      ) : (
        <div id={`${id}-list`} className="flex flex-col gap-2">
          {slice.map((c, sliceIndex) => {
            const ready = isReady(c);
            // Render a group label before the first not-ready card on this page
            // so the de-emphasized group reads as a distinct section.
            const prev = slice[sliceIndex - 1];
            const showGroupDivider = !ready && (sliceIndex === 0 || (prev ? isReady(prev) : false));

            if (!ready) {
              return (
                <div key={c.id} id={`${id}-group-${c.id}`} className="flex flex-col gap-2">
                  {showGroupDivider && (
                    <div
                      id={`${id}-notready-label`}
                      className="mt-2 font-mono text-[10.5px] text-text-faint uppercase tracking-[0.16em]"
                    >
                      Not ready yet · no signal to compare
                    </div>
                  )}
                  <div
                    id={`${id}-card-${c.id}`}
                    aria-disabled="true"
                    className="grid grid-cols-[24px_36px_minmax(0,1fr)_minmax(160px,auto)] items-center gap-3 rounded-[12px] border border-border border-dashed bg-surface px-3.5 py-3 text-left opacity-60"
                  >
                    <span
                      id={`${id}-card-${c.id}-lock`}
                      aria-hidden
                      className="flex h-[18px] w-[18px] items-center justify-center text-text-faint"
                    >
                      <Lock strokeWidth={1.75} className="h-3 w-3" />
                    </span>
                    <span
                      id={`${id}-card-${c.id}-avatar`}
                      aria-hidden
                      className="flex h-9 w-9 items-center justify-center rounded-full font-mono text-[11px] grayscale"
                      style={{ background: c.color, color: pickAvatarFg(c.color) }}
                    >
                      {c.avatar}
                    </span>
                    <span id={`${id}-card-${c.id}-body`} className="min-w-0">
                      <span
                        id={`${id}-card-${c.id}-name`}
                        className="block truncate font-medium font-sans text-[14px] text-text-secondary"
                      >
                        {c.name}
                      </span>
                      <span
                        id={`${id}-card-${c.id}-reason`}
                        className="mt-0.5 block truncate text-[12px] text-text-muted"
                      >
                        {notReadyReason(c)}
                      </span>
                    </span>
                    <span
                      id={`${id}-card-${c.id}-flag`}
                      className="text-right font-mono text-[11px] text-text-muted"
                    >
                      <span id={`${id}-card-${c.id}-flag-top`} className="block">
                        Not selectable
                      </span>
                      <span id={`${id}-card-${c.id}-flag-bot`} className="mt-0.5 block">
                        {c.scoresIn}/{c.rounds} rounds done
                      </span>
                    </span>
                  </div>
                </div>
              );
            }

            const isSelected = selected.includes(c.id);
            const canPick = isCompatible(c);
            const rated = ratedCount(c);
            return (
              <button
                key={c.id}
                id={`${id}-card-${c.id}`}
                type="button"
                aria-pressed={isSelected}
                disabled={!canPick}
                title={
                  canPick
                    ? undefined
                    : `Has ${rated} rated round${rated === 1 ? '' : 's'} — pick candidates with ${anchorCount} to compare fairly`
                }
                onClick={() => {
                  if (canPick) onToggle(c.id);
                }}
                className={cn(
                  'grid grid-cols-[24px_36px_minmax(0,1fr)_minmax(160px,auto)] items-center gap-3 rounded-[12px] border bg-white px-3.5 py-3 text-left transition-colors',
                  isSelected
                    ? 'border-text-primary bg-surface-accent shadow-[0_0_0_2px_rgba(17,17,17,0.06)]'
                    : 'border-border hover:border-text-primary',
                  !canPick && 'cursor-not-allowed opacity-45 hover:border-border',
                )}
              >
                <span
                  id={`${id}-card-${c.id}-check`}
                  aria-hidden
                  className={cn(
                    'flex h-[18px] w-[18px] items-center justify-center rounded border',
                    isSelected
                      ? 'border-text-primary bg-text-primary text-white'
                      : 'border-border bg-white text-transparent',
                  )}
                >
                  {isSelected && <Check strokeWidth={3} className="h-2.5 w-2.5" />}
                </span>
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
                    id={`${id}-card-${c.id}-signal`}
                    className="mt-0.5 block truncate text-[12px] text-text-muted"
                  >
                    {canPick ? signalLine(c) : `Needs ${anchorCount} rated rounds to compare`}
                  </span>
                </span>
                <span
                  id={`${id}-card-${c.id}-flag`}
                  className="text-right font-mono text-[11px] text-text-secondary"
                >
                  <span id={`${id}-card-${c.id}-flag-top`} className="block text-text-primary">
                    {canPick ? c.flag : 'Round count differs'}
                  </span>
                  <span id={`${id}-card-${c.id}-flag-bot`} className="mt-0.5 block text-text-muted">
                    {rated} rated round{rated === 1 ? '' : 's'}
                  </span>
                </span>
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
            Showing {safePage * pageSize + 1}–{Math.min(filtered.length, (safePage + 1) * pageSize)}{' '}
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
          Pick 2 or more <b className="font-medium text-text-primary">ready</b> candidates with the{' '}
          <b className="font-medium text-text-primary">same number of rated rounds</b> — comparing
          candidates who sat a different number of interviews wouldn&apos;t be a fair debrief.
        </div>
        <div id={`${id}-actions`} className="flex items-center gap-2">
          <button
            id={`${id}-cancel`}
            type="button"
            onClick={onCancel}
            className="inline-flex items-center rounded-full border border-border bg-white px-3.5 py-2 font-medium font-sans text-[13px] text-text-primary transition-colors hover:border-text-primary"
          >
            Cancel
          </button>
          <button
            id={`${id}-confirm`}
            type="button"
            onClick={onConfirm}
            disabled={!canConfirm}
            className={cn(
              'inline-flex items-center rounded-full border px-3.5 py-2 font-medium font-sans text-[13px] transition-colors',
              canConfirm
                ? 'border-text-primary bg-text-primary text-white hover:bg-[#222]'
                : 'cursor-not-allowed border-border bg-surface text-text-faint',
            )}
          >
            {canConfirm ? `Prepare debrief · ${readySelectedCount}` : 'Prepare debrief'}
          </button>
        </div>
      </div>
    </div>
  );
}
