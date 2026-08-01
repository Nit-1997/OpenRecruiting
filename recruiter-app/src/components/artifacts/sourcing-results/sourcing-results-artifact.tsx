'use client';

import {
  ChevronLeft,
  ChevronRight,
  Code2,
  Database,
  Download,
  Mail,
  Network,
  UserPlus,
  X,
} from 'lucide-react';
import type { FC, ReactElement } from 'react';
import { useMemo, useState } from 'react';
import type { SourcingCriteria } from '@/fixtures/sourcing-queries';
import { SOURCING_CRITERIA_LABELS } from '@/fixtures/sourcing-queries';
import type { CandidateSource, SourcingCandidate } from '@/fixtures/sourcing-results';
import { TOTAL_MATCH_COUNT_LABEL } from '@/fixtures/sourcing-results';
import { cn, pickAvatarFg } from '@/lib/utils';
import { useTypedArtifact } from '../_shared/use-artifact-data';

export type SourcingResultsPillKey = keyof SourcingCriteria | `skill:${string}`;

export interface SourcingResultsArtifactData {
  criteria: SourcingCriteria;
  roleLabel?: string | null;
  candidates: SourcingCandidate[];
  selectedIds: string[];
  totalMatchesLabel: string;
  page: number;
  pageSize: number;
}

interface SourcingResultsArtifactProps {
  id: string;
  artifactId: string;
  onRemoveFilter?: (pill: SourcingResultsPillKey) => void;
  onToggleCandidate?: (candidateId: string) => void;
  onPageChange?: (page: number) => void;
  onAddSelectedToPipeline?: () => void;
  onSendOutreach?: () => void;
  onExport?: () => void;
}

const SOURCE_ICONS: Record<CandidateSource, FC<{ className?: string }>> = {
  linkedin: ({ className }: { className?: string }): ReactElement => (
    <Network strokeWidth={1.75} className={className} aria-hidden />
  ),
  github: ({ className }: { className?: string }): ReactElement => (
    <Code2 strokeWidth={1.75} className={className} aria-hidden />
  ),
  ats: ({ className }: { className?: string }): ReactElement => (
    <Database strokeWidth={1.75} className={className} aria-hidden />
  ),
};

const SOURCE_LABELS: Record<CandidateSource, string> = {
  linkedin: 'LinkedIn',
  github: 'GitHub',
  ats: 'ATS',
};

const DEFAULT_PAGE_SIZE = 8;

function scoreTone(score: number): { ring: string; text: string; bg: string } {
  if (score >= 90) return { ring: 'ring-[#047857]/40', text: 'text-[#047857]', bg: 'bg-[#ECFDF5]' };
  if (score >= 80) return { ring: 'ring-[#1D4ED8]/40', text: 'text-[#1D4ED8]', bg: 'bg-[#EFF6FF]' };
  if (score >= 70) return { ring: 'ring-[#B45309]/40', text: 'text-[#B45309]', bg: 'bg-[#FFFBEB]' };
  return { ring: 'ring-[#6B7280]/40', text: 'text-[#6B7280]', bg: 'bg-surface' };
}

export function SourcingResultsArtifact({
  id,
  artifactId,
  onRemoveFilter,
  onToggleCandidate,
  onPageChange,
  onAddSelectedToPipeline,
  onSendOutreach,
  onExport,
}: SourcingResultsArtifactProps) {
  const artifact = useTypedArtifact(artifactId, 'sourcing-results');
  const data: Partial<SourcingResultsArtifactData> = artifact?.data ?? {};
  const [sort, setSort] = useState<'match' | 'yoe'>('match');

  const candidates = data.candidates ?? [];
  const selectedIds = useMemo(() => new Set(data.selectedIds ?? []), [data.selectedIds]);
  const criteria = data.criteria ?? {};
  const totalLabel = data.totalMatchesLabel ?? TOTAL_MATCH_COUNT_LABEL;
  const pageSize = data.pageSize ?? DEFAULT_PAGE_SIZE;
  const roleLabel = data.roleLabel ?? null;
  const isBuilding = artifact?.isBuilding ?? false;

  const sorted = useMemo(() => {
    const copy = [...candidates];
    if (sort === 'yoe') copy.sort((a, b) => b.yoe - a.yoe);
    else copy.sort((a, b) => b.matchScore - a.matchScore);
    return copy;
  }, [candidates, sort]);

  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize));
  const page = Math.min(data.page ?? 0, pageCount - 1);
  const pageItems = sorted.slice(page * pageSize, page * pageSize + pageSize);

  if (!artifact) return null;

  const pills = buildFilterPills(criteria);

  return (
    <section
      id={id}
      aria-busy={isBuilding}
      aria-label="Sourcing results artifact"
      className="flex min-w-0 flex-col"
    >
      {roleLabel && (
        <div
          id={`${id}-role-label`}
          className="mb-3 inline-flex w-fit items-center gap-2 rounded-full border border-border/70 bg-white/85 shadow-[0_1px_2px_rgba(0,0,0,0.04)] backdrop-blur-sm px-3 py-1.5 font-mono text-[10.5px] text-text-secondary uppercase tracking-[0.14em]"
        >
          <span id={`${id}-role-label-eyebrow`} className="text-text-faint">
            Sourcing for
          </span>
          <span id={`${id}-role-label-text`} className="font-medium text-text-primary">
            {roleLabel}
          </span>
        </div>
      )}

      <FilterStrip id={`${id}-filters`} pills={pills} onRemove={onRemoveFilter ?? (() => {})} />

      <header
        id={`${id}-head`}
        className="mb-4 flex flex-wrap items-end justify-between gap-3 border-border border-b pb-3"
      >
        <div id={`${id}-head-left`} className="min-w-0">
          <div
            id={`${id}-eyebrow`}
            className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]"
          >
            Sourcing results
          </div>
          <h2
            id={`${id}-headline`}
            className="mt-1 font-display text-[22px] text-text-primary leading-tight tracking-[-0.005em]"
          >
            Found {totalLabel} matches
            <span className="ml-1 text-[15px] text-text-muted">· showing top {sorted.length}</span>
          </h2>
          <div id={`${id}-subhead`} className="mt-1 text-[12.5px] text-text-muted">
            {selectedIds.size} selected
          </div>
        </div>
        <div id={`${id}-head-right`} className="flex shrink-0 items-center gap-2">
          <label
            id={`${id}-sort-label`}
            htmlFor={`${id}-sort`}
            className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]"
          >
            Sort
          </label>
          <select
            id={`${id}-sort`}
            value={sort}
            onChange={(e) => setSort(e.target.value === 'yoe' ? 'yoe' : 'match')}
            className="rounded-full border border-border/70 bg-white/85 shadow-[0_1px_2px_rgba(0,0,0,0.04)] backdrop-blur-sm px-3 py-1 font-mono text-[11px] text-text-primary focus:outline-none"
          >
            <option value="match">Match score</option>
            <option value="yoe">Years of experience</option>
          </select>
        </div>
      </header>

      <CandidateList
        id={`${id}-list`}
        items={pageItems}
        selectedIds={selectedIds}
        onToggle={onToggleCandidate ?? (() => {})}
      />

      {pageCount > 1 && (
        <Pager
          id={`${id}-pager`}
          page={page}
          pageCount={pageCount}
          onPageChange={onPageChange ?? (() => {})}
        />
      )}

      <ActionsBar
        id={`${id}-actions`}
        selectedCount={selectedIds.size}
        onAdd={onAddSelectedToPipeline ?? (() => {})}
        onOutreach={onSendOutreach ?? (() => {})}
        onExport={onExport ?? (() => {})}
      />

      {isBuilding && (
        <div
          id={`${id}-building`}
          className="mt-4 flex items-center gap-2 font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]"
        >
          <span
            id={`${id}-building-dot`}
            aria-hidden
            className="h-1.5 w-1.5 animate-pulse rounded-full bg-cortex-500"
          />
          Streaming candidates...
        </div>
      )}
    </section>
  );
}

interface FilterPill {
  key: SourcingResultsPillKey;
  label: string;
  prefix?: string;
}

function buildFilterPills(criteria: SourcingCriteria): FilterPill[] {
  const out: FilterPill[] = [];
  if (criteria.title)
    out.push({ key: 'title', label: criteria.title, prefix: SOURCING_CRITERIA_LABELS.title });
  if (criteria.location) out.push({ key: 'location', label: criteria.location, prefix: 'in' });
  if (criteria.yoe) out.push({ key: 'yoe', label: criteria.yoe, prefix: 'with' });
  if (criteria.industry) out.push({ key: 'industry', label: criteria.industry, prefix: 'focus' });
  if (criteria.skills) {
    for (const skill of criteria.skills) {
      out.push({ key: `skill:${skill}`, label: skill, prefix: 'skill' });
    }
  }
  return out;
}

function FilterStrip({
  id,
  pills,
  onRemove,
}: {
  id: string;
  pills: FilterPill[];
  onRemove: (pill: SourcingResultsPillKey) => void;
}) {
  if (pills.length === 0) {
    return (
      <div
        id={id}
        className="sticky top-0 z-[1] mb-4 flex items-center gap-2 border-border border-b bg-white py-2.5 text-[12px] text-text-muted"
      >
        No filters applied — showing all candidates.
      </div>
    );
  }
  return (
    <div
      id={id}
      className="sticky top-0 z-[1] mb-4 flex flex-wrap gap-2 border-border border-b bg-white py-2.5"
    >
      {pills.map((p) => (
        <button
          key={p.key}
          id={`${id}-pill-${p.key}`}
          type="button"
          onClick={() => onRemove(p.key)}
          className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-3 py-1 font-sans text-[12px] text-text-primary transition-colors hover:border-text-primary"
        >
          {p.prefix && (
            <span
              id={`${id}-pill-${p.key}-prefix`}
              className="font-mono text-[10px] text-text-faint uppercase tracking-[0.12em]"
            >
              {p.prefix}
            </span>
          )}
          <span id={`${id}-pill-${p.key}-label`} className="font-medium">
            {p.label}
          </span>
          <X strokeWidth={1.75} className="h-3 w-3 text-text-muted" aria-hidden />
        </button>
      ))}
    </div>
  );
}

function CandidateList({
  id,
  items,
  selectedIds,
  onToggle,
}: {
  id: string;
  items: SourcingCandidate[];
  selectedIds: Set<string>;
  onToggle: (candidateId: string) => void;
}) {
  if (items.length === 0) {
    return (
      <div
        id={`${id}-empty`}
        className="rounded-[14px] border border-border border-dashed bg-white px-5 py-10 text-center text-[13px] text-text-muted"
      >
        No candidates match the current filters. Clear a pill to widen the search.
      </div>
    );
  }
  return (
    <ul id={id} className="flex flex-col gap-3">
      {items.map((c) => (
        <CandidateCard
          key={c.id}
          id={`${id}-card-${c.id}`}
          candidate={c}
          checked={selectedIds.has(c.id)}
          onToggle={onToggle}
        />
      ))}
    </ul>
  );
}

function CandidateCard({
  id,
  candidate,
  checked,
  onToggle,
}: {
  id: string;
  candidate: SourcingCandidate;
  checked: boolean;
  onToggle: (candidateId: string) => void;
}) {
  const SourceIcon = SOURCE_ICONS[candidate.source];
  const scoreStyle = scoreTone(candidate.matchScore);
  return (
    <li id={id} className="list-none">
      <article
        id={`${id}-body`}
        className={cn(
          'flex items-stretch gap-3 rounded-[14px] border bg-white px-4 py-3.5 transition-colors',
          checked ? 'border-text-primary bg-surface' : 'border-border hover:border-text-primary',
        )}
      >
        <label
          id={`${id}-check`}
          htmlFor={`${id}-check-input`}
          className="flex shrink-0 cursor-pointer items-start pt-1"
        >
          <input
            id={`${id}-check-input`}
            type="checkbox"
            checked={checked}
            onChange={() => onToggle(candidate.id)}
            className="h-4 w-4 shrink-0 cursor-pointer accent-text-primary"
            aria-label={`Select ${candidate.name}`}
          />
        </label>
        <div
          id={`${id}-avatar`}
          aria-hidden
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full font-medium font-mono text-[13px] text-text-primary"
          style={{ background: candidate.color, color: pickAvatarFg(candidate.color) }}
        >
          {candidate.avatar}
        </div>
        <div id={`${id}-main`} className="min-w-0 flex-1">
          <div id={`${id}-row-1`} className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <h4
              id={`${id}-name`}
              className="font-medium font-sans text-[14px] text-text-primary leading-tight"
            >
              {candidate.name}
            </h4>
            <span
              id={`${id}-source`}
              className="inline-flex items-center gap-1 rounded-full border border-border bg-surface px-2 py-0.5 font-mono text-[10px] text-text-muted uppercase tracking-[0.12em]"
            >
              <SourceIcon className="h-3 w-3" />
              {SOURCE_LABELS[candidate.source]}
            </span>
          </div>
          <div
            id={`${id}-meta`}
            className="mt-0.5 font-mono text-[10.5px] text-text-secondary uppercase tracking-[0.12em]"
          >
            {candidate.title} · {candidate.company} · {candidate.location} · {candidate.yoe} yoe
          </div>
          <p
            id={`${id}-headline`}
            className="mt-1.5 text-[12.5px] text-text-secondary leading-[1.5]"
          >
            {candidate.headline}
          </p>
          <ul id={`${id}-skills`} className="mt-2 flex flex-wrap gap-1.5">
            {candidate.skills.slice(0, 5).map((s) => (
              <li
                key={s}
                id={`${id}-skill-${s.toLowerCase().replace(/[^a-z0-9]/g, '-')}`}
                className="rounded-full bg-surface px-2 py-0.5 font-mono text-[10px] text-text-secondary"
              >
                {s}
              </li>
            ))}
          </ul>
        </div>
        <div id={`${id}-score-wrap`} className="flex shrink-0 flex-col items-end gap-1">
          <div
            id={`${id}-score`}
            className={cn(
              'flex h-11 w-11 items-center justify-center rounded-full font-medium font-mono text-[13px] ring-2',
              scoreStyle.bg,
              scoreStyle.text,
              scoreStyle.ring,
            )}
          >
            {candidate.matchScore}
          </div>
          <span
            id={`${id}-score-label`}
            className="font-mono text-[9px] text-text-faint uppercase tracking-[0.12em]"
          >
            Match
          </span>
        </div>
      </article>
    </li>
  );
}

function Pager({
  id,
  page,
  pageCount,
  onPageChange,
}: {
  id: string;
  page: number;
  pageCount: number;
  onPageChange: (page: number) => void;
}) {
  return (
    <div
      id={id}
      className="mt-5 flex items-center justify-between font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]"
    >
      <span id={`${id}-stat`}>
        Page {page + 1} of {pageCount}
      </span>
      <div id={`${id}-ctrls`} className="flex items-center gap-1.5">
        <button
          id={`${id}-prev`}
          type="button"
          aria-label="Previous page"
          disabled={page === 0}
          onClick={() => onPageChange(Math.max(0, page - 1))}
          className="flex h-7 w-7 items-center justify-center rounded-full border border-border/70 bg-white/85 shadow-[0_1px_2px_rgba(0,0,0,0.04)] backdrop-blur-sm text-text-muted transition-colors hover:border-text-primary hover:text-text-primary disabled:opacity-40"
        >
          <ChevronLeft strokeWidth={1.75} className="h-3.5 w-3.5" />
        </button>
        {Array.from({ length: pageCount }).map((_, i) => (
          <button
            // biome-ignore lint/suspicious/noArrayIndexKey: page numbers are stable
            key={i}
            id={`${id}-dot-${i}`}
            type="button"
            onClick={() => onPageChange(i)}
            className={cn(
              'flex h-7 min-w-7 items-center justify-center rounded-full border px-2 font-mono text-[11px] transition-colors',
              i === page
                ? 'border-text-primary bg-text-primary text-white'
                : 'border-border bg-white text-text-muted hover:border-text-primary hover:text-text-primary',
            )}
          >
            {i + 1}
          </button>
        ))}
        <button
          id={`${id}-next`}
          type="button"
          aria-label="Next page"
          disabled={page >= pageCount - 1}
          onClick={() => onPageChange(Math.min(pageCount - 1, page + 1))}
          className="flex h-7 w-7 items-center justify-center rounded-full border border-border/70 bg-white/85 shadow-[0_1px_2px_rgba(0,0,0,0.04)] backdrop-blur-sm text-text-muted transition-colors hover:border-text-primary hover:text-text-primary disabled:opacity-40"
        >
          <ChevronRight strokeWidth={1.75} className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

function ActionsBar({
  id,
  selectedCount,
  onAdd,
  onOutreach,
  onExport,
}: {
  id: string;
  selectedCount: number;
  onAdd: () => void;
  onOutreach: () => void;
  onExport: () => void;
}) {
  const hasSelection = selectedCount > 0;
  return (
    <footer
      id={id}
      className="mt-5 flex flex-wrap items-center justify-between gap-3 border-border border-t pt-4"
    >
      <div id={`${id}-meta`} className="text-[12px] text-text-muted leading-[1.4]">
        {hasSelection
          ? `${selectedCount} candidate${selectedCount === 1 ? '' : 's'} ready to action.`
          : 'Select candidates above to enable pipeline, outreach, and export actions.'}
      </div>
      <div id={`${id}-btns`} className="flex flex-wrap items-center gap-2">
        <button
          id={`${id}-add`}
          type="button"
          onClick={onAdd}
          disabled={!hasSelection}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 font-medium font-sans text-[12.5px] transition-colors',
            hasSelection
              ? 'border-text-primary bg-text-primary text-white hover:bg-[#222]'
              : 'cursor-not-allowed border-border bg-white text-text-muted opacity-60',
          )}
          title="Add the selected candidates to the role pipeline"
        >
          <UserPlus strokeWidth={1.75} className="h-3.5 w-3.5" />
          Add {hasSelection ? `${selectedCount} ` : ''}to pipeline
        </button>
        <button
          id={`${id}-outreach`}
          type="button"
          onClick={onOutreach}
          disabled={!hasSelection}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 font-medium font-sans text-[12.5px] transition-colors',
            hasSelection
              ? 'border-text-primary bg-white text-text-primary hover:bg-surface'
              : 'cursor-not-allowed border-border bg-white text-text-muted opacity-60',
          )}
          title="Send outreach to the selected candidates"
        >
          <Mail strokeWidth={1.75} className="h-3.5 w-3.5" />
          Send outreach
        </button>
        <button
          id={`${id}-export`}
          type="button"
          onClick={onExport}
          className="inline-flex items-center gap-1.5 rounded-full border border-border/70 bg-white/85 shadow-[0_1px_2px_rgba(0,0,0,0.04)] backdrop-blur-sm px-3 py-1.5 font-medium font-sans text-[12.5px] text-text-primary transition-colors hover:border-text-primary"
          title="Export is a stub in this demo"
        >
          <Download strokeWidth={1.75} className="h-3.5 w-3.5" />
          Export
        </button>
      </div>
    </footer>
  );
}
