'use client';

import { Calendar, CheckCircle2, Circle, Clock3, Sparkles, X } from 'lucide-react';
import { PipelineSkeleton } from '@/components/shell/skeletons';
import type {
  Candidate,
  CandidateRoundStatus,
  PipelineCandidateRound,
  PipelineRoundHeader,
  Requisition,
  RoundRating,
} from '@/domain';
import { useCandidatesForRequisition } from '@/hooks/use-services';
import { formatScheduledDate } from '@/lib/format-scheduled';
import { cn, pickAvatarFg } from '@/lib/utils';

interface PipelineTabProps {
  id: string;
  role: Requisition;
  onCellClick: (candidateId: string, roundId: string) => void;
}

export function PipelineTab({ id, role, onCellClick }: PipelineTabProps) {
  const { data: cands } = useCandidatesForRequisition(role.id);

  // Cold load (no cached data yet) → content-shaped skeleton. A warm revisit
  // has `cands` from the cache and renders rows immediately. `cands === []`
  // (loaded, genuinely empty) still falls through to the empty state below.
  if (!cands) {
    return <PipelineSkeleton id={id} />;
  }
  const allCands = cands;

  if (allCands.length === 0) {
    return (
      <div
        id={id}
        className="rounded-[16px] border border-border border-dashed bg-white p-12 text-center"
      >
        <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-surface text-text-muted">
          <Circle strokeWidth={1.75} className="h-4 w-4" />
        </div>
        <p className="text-[13.5px] text-text-primary">No candidates in this pipeline yet.</p>
        <p className="mt-1 text-[12.5px] text-text-muted">
          Add someone in the Candidates tab to start the loop.
        </p>
      </div>
    );
  }

  return (
    <div id={id} className="flex flex-col gap-3">
      {allCands.map((c) => (
        <PipelineRow
          key={c.id}
          id={`${id}-row-${c.id}`}
          role={role}
          candidate={c}
          onCellClick={onCellClick}
        />
      ))}
    </div>
  );
}

function PipelineRow({
  id,
  role,
  candidate,
  onCellClick,
}: {
  id: string;
  role: Requisition;
  candidate: Candidate;
  onCellClick: (candidateId: string, roundId: string) => void;
}) {
  // Spec §7: pipeline RPC nests each candidate's ordered candidate_rounds
  // *with the round header embedded*. Drive the rail off this data — no
  // per-row listRounds fetch, and custom rounds render naturally (they're
  // absent from /plan but always present in candidate_rounds).
  const pipelineRounds: PipelineCandidateRound[] = candidate.candidate_rounds ?? [];
  const candidateRounds: PipelineRoundHeader[] = pipelineRounds.map((cr) => cr.round);
  const byRound = new Map(pipelineRounds.map((cr) => [cr.round_id, cr] as const));
  const total = candidateRounds.length;
  const done = candidateRounds.filter((r) => byRound.get(r.id)?.status === 'completed').length;
  const scheduledRound =
    candidateRounds.find((r) => byRound.get(r.id)?.status === 'scheduled') ?? null;
  const scheduledCr = scheduledRound ? byRound.get(scheduledRound.id) : null;
  const nextPending = candidateRounds.find((r) => {
    const cr = byRound.get(r.id);
    return !cr || cr.status === 'pending';
  });
  const lastCompleted = [...candidateRounds]
    .reverse()
    .find((r) => byRound.get(r.id)?.status === 'completed');
  const defaultRoundId =
    scheduledRound?.id ?? lastCompleted?.id ?? nextPending?.id ?? candidateRounds[0]?.id ?? null;
  // `role` retained for future header use but no longer needed for round lookups.
  void role;

  const openCardPacket = () => {
    if (defaultRoundId) onCellClick(candidate.id, defaultRoundId);
  };

  return (
    <article
      id={id}
      role="button"
      tabIndex={0}
      aria-label={`Open packet for ${candidate.name}`}
      onClick={openCardPacket}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          openCardPacket();
        }
      }}
      className="cursor-pointer rounded-[16px] border border-border bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition-shadow hover:shadow-[0_2px_8px_rgba(0,0,0,0.04)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-text-primary focus-visible:ring-offset-2"
    >
      <header id={`${id}-head`} className="flex flex-wrap items-center justify-between gap-3">
        <div id={`${id}-ident`} className="flex min-w-0 items-center gap-3">
          <span
            aria-hidden
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full font-mono text-[13px] text-text-primary"
            style={{ background: candidate.avatar_color, color: pickAvatarFg(candidate.avatar_color) }}
          >
            {candidate.avatar_initials}
          </span>
          <div className="min-w-0">
            <div className="truncate font-medium font-sans text-[15px] text-text-primary">
              {candidate.name}
            </div>
            <div className="mt-0.5 flex items-center gap-2 font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
              {/* candidate.status: backend canonical ('active'|'hired'|'rejected'|'withdrawn').
                  Currently flipped via candidates.setStatus(...); no debrief surface yet. */}
              <span>{candidate.status}</span>
              <span aria-hidden>·</span>
              <span>
                {done}/{total} rounds
              </span>
            </div>
          </div>
        </div>
        <div id={`${id}-progress`} className="flex items-center gap-3">
          {scheduledRound && scheduledCr?.scheduled_at ? (
            <button
              id={`${id}-next`}
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onCellClick(candidate.id, scheduledRound.id);
              }}
              className="inline-flex items-center gap-1.5 rounded-full border border-[#BFDBFE] bg-[#EFF6FF] px-3 py-1 font-medium font-sans text-[11.5px] text-[#1D4ED8] transition-colors hover:border-[#1D4ED8]"
            >
              <Calendar strokeWidth={1.75} className="h-3 w-3" />
              {formatScheduledDate(
                scheduledCr.scheduled_at,
                scheduledCr.scheduling_timezone,
              )}
              <span className="font-normal text-[#1D4ED8]/70">·</span>
              <span className="font-normal">{scheduledRound.name}</span>
            </button>
          ) : !nextPending ? (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[#A7F3D0] bg-[#ECFDF5] px-3 py-1 font-mono text-[10.5px] text-[#047857] uppercase tracking-[0.14em]">
              <CheckCircle2 strokeWidth={1.75} className="h-3 w-3" />
              Loop complete
            </span>
          ) : null}
        </div>
      </header>

      <div id={`${id}-steps`} className="mt-5">
        <StageRail
          id={`${id}-stages`}
          rounds={candidateRounds}
          byRound={byRound}
          onNodeClick={(roundId) => onCellClick(candidate.id, roundId)}
        />
      </div>
    </article>
  );
}

const STATUS_NODE: Record<
  CandidateRoundStatus,
  { ring: string; fill: string; text: string; glow: string }
> = {
  completed: {
    ring: 'border-[#047857]',
    fill: 'bg-[#ECFDF5]',
    text: 'text-[#047857]',
    glow: 'shadow-[0_0_0_3px_rgba(16,185,129,0.08)]',
  },
  scheduled: {
    ring: 'border-[#1D4ED8]',
    fill: 'bg-[#EFF6FF]',
    text: 'text-[#1D4ED8]',
    glow: 'shadow-[0_0_0_3px_rgba(29,78,216,0.08)]',
  },
  pending: {
    ring: 'border-text-faint/60',
    fill: 'bg-white',
    text: 'text-text-muted',
    glow: '',
  },
  in_progress: {
    ring: 'border-[#1D4ED8]',
    fill: 'bg-[#EFF6FF]',
    text: 'text-[#1D4ED8]',
    glow: 'shadow-[0_0_0_3px_rgba(29,78,216,0.12)]',
  },
  cancelled: {
    ring: 'border-[#B91C1C]',
    fill: 'bg-[#FEF2F2]',
    text: 'text-[#B91C1C]',
    glow: '',
  },
};

const RATING_DOT: Record<RoundRating, string> = {
  strong_yes: 'bg-[#059669]',
  yes: 'bg-[#34D399]',
  maybe: 'bg-[#F59E0B]',
  no: 'bg-[#F87171]',
  strong_no: 'bg-[#B91C1C]',
};

function StageRail({
  id,
  rounds,
  byRound,
  onNodeClick,
}: {
  id: string;
  rounds: PipelineRoundHeader[];
  byRound: Map<string, PipelineCandidateRound>;
  onNodeClick: (roundId: string) => void;
}) {
  return (
    <ol
      id={id}
      className="relative flex items-start gap-1 overflow-x-auto overflow-y-visible px-1 pt-2 pb-2"
      aria-label="Stage progression"
    >
      {rounds.map((r, i) => {
        const cr = byRound.get(r.id);
        const status: CandidateRoundStatus = cr?.status ?? 'pending';
        const nextCr = rounds[i + 1] ? byRound.get(rounds[i + 1]?.id ?? '') : null;
        const nextStatus: CandidateRoundStatus | null = nextCr?.status ?? null;
        const connectorActive = status === 'completed';
        const custom = !!r.is_custom;
        return (
          <li
            key={r.id}
            id={`${id}-step-${r.id}`}
            className="flex min-w-[120px] flex-1 flex-col items-center"
          >
            <div className="relative flex w-full items-center">
              {i > 0 && (
                <span
                  aria-hidden
                  className={cn(
                    'absolute top-1/2 right-1/2 z-0 h-0.5 w-full -translate-y-1/2',
                    status === 'completed' || status === 'scheduled' ? 'bg-[#10B981]' : 'bg-border',
                  )}
                />
              )}
              {i < rounds.length - 1 && (
                <span
                  aria-hidden
                  className={cn(
                    'absolute top-1/2 left-1/2 z-0 h-0.5 w-full -translate-y-1/2',
                    connectorActive && nextStatus !== null ? 'bg-[#10B981]' : 'bg-border',
                  )}
                />
              )}
              <PipelineNode
                id={`${id}-node-${r.id}`}
                roundNumber={i + 1}
                status={status}
                rating={cr?.rating ?? null}
                custom={custom}
                onClick={(e) => {
                  e.stopPropagation();
                  onNodeClick(r.id);
                }}
              />
            </div>
            <button
              id={`${id}-meta-${r.id}`}
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onNodeClick(r.id);
              }}
              className="mt-2 w-full text-center"
            >
              <div
                className={cn(
                  'flex items-center justify-center gap-1 truncate font-medium font-sans text-[11.5px]',
                  custom ? 'text-[#B45309]' : 'text-text-primary',
                )}
              >
                {custom && (
                  <Sparkles aria-hidden strokeWidth={1.75} className="h-3 w-3 text-[#B45309]" />
                )}
                <span className="truncate">{r.name}</span>
              </div>
              <div className="mt-0.5 truncate font-mono text-[10px] uppercase tracking-[0.14em]">
                {cr?.status === 'scheduled' && cr.scheduled_at ? (
                  <span className="text-text-muted">
                    {formatScheduledDate(cr.scheduled_at, cr.scheduling_timezone)}
                  </span>
                ) : cr?.status === 'completed' || cr?.status === 'cancelled' || cr?.status === 'in_progress' ? (
                  <span className="text-text-muted">{cr.status}</span>
                ) : (
                  <span className="text-text-primary underline decoration-text-primary/40 underline-offset-2 hover:decoration-text-primary">
                    Schedule
                  </span>
                )}
              </div>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

const CUSTOM_NODE = {
  ring: 'border-[#F59E0B]',
  fill: 'bg-[#FFFBEB]',
  text: 'text-[#B45309]',
  glow: 'shadow-[0_0_0_3px_rgba(245,158,11,0.12)]',
};

function PipelineNode({
  id,
  roundNumber,
  status,
  rating,
  custom,
  onClick,
}: {
  id: string;
  roundNumber: number;
  status: CandidateRoundStatus;
  rating: RoundRating | null;
  custom: boolean;
  onClick: (e: React.MouseEvent<HTMLButtonElement>) => void;
}) {
  const style = custom ? CUSTOM_NODE : STATUS_NODE[status];
  const icon =
    status === 'completed' ? (
      <CheckCircle2 strokeWidth={2} className="h-4 w-4" />
    ) : status === 'cancelled' ? (
      <X strokeWidth={2} className="h-3.5 w-3.5" />
    ) : status === 'scheduled' ? (
      <Clock3 strokeWidth={2} className="h-3.5 w-3.5" />
    ) : (
      <span className="font-medium font-mono text-[11px]">{roundNumber}</span>
    );
  return (
    <button
      id={id}
      type="button"
      onClick={onClick}
      aria-label={`Round ${roundNumber}${custom ? ' (custom)' : ''}, status ${status}`}
      className={cn(
        'group relative z-10 mx-auto flex h-8 w-8 items-center justify-center rounded-full border-2 bg-white transition-all hover:scale-110',
        style.ring,
        style.fill,
        style.text,
        style.glow,
      )}
    >
      {icon}
      {rating && (
        <span
          aria-hidden
          className={cn(
            'absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border border-white',
            RATING_DOT[rating],
          )}
        />
      )}
    </button>
  );
}
