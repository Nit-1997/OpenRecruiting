'use client';

import {
  AlertTriangle,
  Calendar,
  CheckCircle2,
  ChevronDown,
  ClipboardList,
  Download,
  FileText,
  Mail,
  Maximize2,
  Mic,
  Plus,
  Radio,
  Sparkles,
  Trash2,
  Users,
  Video,
  X,
  XCircle,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { BrandIcon } from '@/components/icons/brand-icons';
import { AuthenticityPanel } from '@/components/screening/authenticity-panel';
import { PacketPaneSkeleton } from '@/components/shell/skeletons';
import { useConfirm } from '@/components/ui/confirm-dialog';
import type {
  CandidateRound,
  CustomRoundCreateInput,
  EvidenceStatus,
  FeedbackEntry,
  Round,
  RoundRating,
  RoundType,
  TranscriptSegment,
} from '@/domain';
import { usePacket, useRecording, useRequisition, useUntrackedPacket } from '@/hooks/use-services';
import { ROLLUP_ICON } from '@/lib/feedback-rollup';
import { formatScheduledDate, formatScheduledTime } from '@/lib/format-scheduled';
import { isCustomRound } from '@/lib/rounds';
import { cn } from '@/lib/utils';
import { candidates as candidateSvc, feedback, interviews } from '@/services';
import { getScreening } from '@/services/screening';
import { ServiceError } from '@/services/service-error';
import { CandidateProfilePanel } from './candidate-profile-panel';
import { ScheduleModal } from './schedule-modal';

interface PacketDrawerProps {
  id: string;
  reqId: string;
  candidateId: string;
  initialRoundId: string | null;
  // View-only mode for surfaces that aren't part of an active hiring
  // pipeline (e.g. untracked-interview captures). Suppresses the
  // "Add custom round" / round-delete / schedule / cancel / request-
  // feedback affordances since none of them apply.
  viewOnly?: boolean;
  // When set, the drawer fetches the captured untracked-interview packet
  // via the dedicated `/api/v2/untracked-interviews/{id}/packet` endpoint
  // instead of the standard role-candidate packet RPC. The RPC doesn't
  // cover materialized-untracked rows, so untracked captures need this
  // alternate fetcher. `reqId` + `candidateId` are still passed through
  // for child components (round rail keys, recording sub-fetches) — they
  // come from the untracked row's `source_*` fields.
  untrackedId?: string;
  // 'overlay' (default) renders the classic fixed right-side slide-over with
  // scrim. 'embedded' renders the same packet UI as a plain block that fills
  // its parent (no fixed positioning, no scrim) — used when the drawer lives
  // INSIDE the agent shell's artifact column so its geometry matches every
  // other workspace artifact and the chat column never reflows.
  variant?: 'overlay' | 'embedded';
  onClose: () => void;
}

const RATING_LABEL: Record<RoundRating, string> = {
  strong_yes: 'Strong yes',
  yes: 'Yes',
  maybe: 'Maybe',
  no: 'No',
  strong_no: 'Strong no',
};

const RATING_CLS: Record<RoundRating, string> = {
  strong_yes: 'bg-[#D1FAE5] text-[#065F46]',
  yes: 'bg-[#DBEAFE] text-[#1E40AF]',
  maybe: 'bg-[#FEF3C7] text-[#92400E]',
  no: 'bg-[#FFE4E6] text-[#9F1239]',
  strong_no: 'bg-[#FEE2E2] text-[#991B1B]',
};

function logErr(err: unknown): void {
  if (err instanceof ServiceError) {
    console.warn(`[packet] ${err.code}: ${err.message}`);
  }
}

export function PacketDrawer({
  id,
  reqId,
  candidateId,
  initialRoundId,
  viewOnly = false,
  untrackedId,
  variant = 'overlay',
  onClose,
}: PacketDrawerProps) {
  // Spec §7: drawer mount fires ONE call to /packet. All read-side state
  // derives from this single response. useRequisition is kept separately
  // for role-level chrome (role_title) that the packet response doesn't
  // include — it's a tiny, well-cached header fetch. Skipped for
  // untracked captures since the materialized requisition isn't readable
  // through /api/v2/roles/{id} and the header label comes from the
  // packet's own round name instead.
  const { data: req } = useRequisition(untrackedId ? null : reqId);
  // Untracked captures go through a dedicated endpoint; everything else
  // goes through the standard candidate-packet RPC. One of the two is
  // always passed a null id and short-circuits in its hook to avoid an
  // unnecessary fetch.
  const standardPacket = usePacket(untrackedId ? null : reqId, untrackedId ? null : candidateId);
  const untrackedPacket = useUntrackedPacket(untrackedId ?? null);
  const packet = untrackedId ? untrackedPacket.data : standardPacket.data;
  const packetLoading = untrackedId ? untrackedPacket.loading : standardPacket.loading;
  const packetError = untrackedId ? untrackedPacket.error : standardPacket.error;

  // Derive the slices the drawer needs from the single packet response.
  // packet.rounds is ordered by round_number (matches the RPC's ORDER BY).
  const allRounds: CandidateRound[] = useMemo(
    () =>
      (packet?.rounds ?? [])
        .map((r) => r.candidate_round)
        .filter((cr): cr is CandidateRound => cr !== null),
    [packet],
  );
  // Rounds visible to this candidate (shared + this candidate's customs),
  // in the same order as candidate_rounds. Drives the round rail labels.
  const visibleRoundDefs: Round[] = useMemo(
    () => (packet?.rounds ?? []).map((r) => r.round),
    [packet],
  );

  const [activeRoundId, setActiveRoundId] = useState<string | null>(initialRoundId);
  const candidateName = packet?.candidate.name ?? '…';

  // The packet RPC carries no screening state, so light-fetch saved screening
  // configs per round (mirrors plan-tab.tsx). `enabled === true` ⇒ OpenRecruiting hosts
  // the round: scheduling it means sending the async screening link, not
  // booking a human interviewer + meeting URL. Skipped for untracked captures
  // (no req-scoped screening) and view-only surfaces.
  const [aiByRound, setAiByRound] = useState<Record<string, boolean>>({});
  const roundIdsKey = allRounds.map((cr) => cr.round_id).join(',');
  useEffect(() => {
    if (untrackedId || viewOnly || !reqId) return;
    const roundIds = roundIdsKey ? roundIdsKey.split(',') : [];
    if (roundIds.length === 0) return;
    let cancelled = false;
    Promise.all(
      roundIds.map((roundId) =>
        getScreening(reqId, roundId)
          .then((cfg) => [roundId, cfg?.enabled === true] as const)
          .catch(() => [roundId, false] as const),
      ),
    ).then((entries) => {
      if (!cancelled) setAiByRound(Object.fromEntries(entries));
    });
    return () => {
      cancelled = true;
    };
  }, [reqId, roundIdsKey, untrackedId, viewOnly]);

  useEffect(() => {
    if (!activeRoundId && allRounds.length > 0) {
      setActiveRoundId(allRounds[0]?.round_id ?? null);
    }
  }, [activeRoundId, allRounds]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const activeCr = allRounds.find((cr) => cr.round_id === activeRoundId) ?? null;
  const activeRound = visibleRoundDefs.find((r) => r.id === activeRoundId) ?? null;

  const embedded = variant === 'embedded';

  return (
    <div
      id={id}
      className={
        embedded
          ? 'relative flex h-full min-h-0 flex-col print:static print:block'
          : 'fixed inset-0 z-40 flex justify-end bg-black/30 print:static print:bg-transparent print:block'
      }
      role="presentation"
    >
      {!embedded && (
        <button
          type="button"
          aria-label="Close packet"
          onClick={onClose}
          className="absolute inset-0 cursor-default bg-transparent print:hidden"
        />
      )}
      <aside
        role={embedded ? 'region' : 'dialog'}
        aria-modal={embedded ? undefined : 'true'}
        aria-labelledby={`${id}-title`}
        className={
          embedded
            ? 'relative flex h-full min-h-0 w-full flex-col overflow-hidden rounded-[14px] border border-border bg-white print:h-auto print:overflow-visible print:border-0'
            : 'relative flex h-full w-full max-w-[960px] flex-col overflow-hidden border-border border-l bg-white shadow-[0_0_80px_rgba(0,0,0,0.2)] print:max-w-none print:h-auto print:overflow-visible print:border-0 print:shadow-none'
        }
      >
        <header className="flex items-start justify-between gap-4 border-border border-b px-4 py-3 sm:px-6 sm:py-4 print:border-b-0">
          <div className="min-w-0">
            <p className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
              {untrackedId ? 'Untracked interview' : 'Feedback packet'}
            </p>
            <h2
              id={`${id}-title`}
              className="mt-1 font-display text-[22px] text-text-primary leading-tight"
            >
              {candidateName}
            </h2>
            <p className="mt-0.5 text-[12.5px] text-text-muted">
              {untrackedId
                ? `${packet?.candidate?.email ?? ''} · ${visibleRoundDefs[0]?.name ?? 'Generic interview'}`
                : `${packet?.candidate?.email ? `${packet.candidate.email} · ` : ''}${req?.role_title ?? 'Role'} · ${allRounds.length} rounds`}
            </p>
          </div>
          <button
            type="button"
            aria-label="Close packet"
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-full text-text-muted hover:bg-surface hover:text-text-primary print:hidden"
          >
            <X strokeWidth={1.75} className="h-4 w-4" />
          </button>
        </header>

        {packet?.candidate?.profile && (
          <div
            id={`${id}-candidate-background`}
            className="shrink-0 border-border border-b bg-surface/30 px-4 py-4 sm:px-6 print:border-b-0 print:bg-transparent"
          >
            <CandidateProfilePanel
              id={`${id}-candidate-profile`}
              profile={packet.candidate.profile}
            />
          </div>
        )}

        <div className="flex min-h-0 flex-1 flex-col md:flex-row print:block">
          <RoundRail
            id={`${id}-rail`}
            reqId={reqId}
            candidateId={candidateId}
            rounds={allRounds}
            roundsByReq={visibleRoundDefs}
            aiByRound={aiByRound}
            activeRoundId={activeRoundId}
            viewOnly={viewOnly}
            onSelect={setActiveRoundId}
            onRoundRemoved={(removedRoundId) => {
              if (activeRoundId === removedRoundId) setActiveRoundId(null);
            }}
          />
          <div className="flex-1 overflow-y-auto bg-surface/30 px-4 py-4 sm:px-6 sm:py-5">
            {activeCr && activeRound ? (
              <RoundPane
                id={`${id}-pane`}
                reqId={reqId}
                candidateId={candidateId}
                candidateName={candidateName}
                roleTitle={req?.role_title ?? ''}
                candidateRound={activeCr}
                round={activeRound}
                viewOnly={viewOnly}
                aiHosted={aiByRound[activeCr.round_id] === true}
                displayRoundNumber={allRounds.findIndex((cr) => cr.round_id === activeRoundId) + 1}
                // The packet RPC returns NULL feedback_questions for rounds
                // without a scorecard yet (e.g. a just-added custom round or a
                // freshly scheduled one) — the domain type says [] but the
                // wire says null, so every dereference must guard.
                questions={(activeRound.feedback_questions ?? []).map((q) => ({
                  id: q.id,
                  heading: q.heading,
                  description: q.description,
                }))}
                // Spec §7: feedback entries are derived from the single
                // /packet response. Flatten the per-question feedback_entries
                // for the active round into a flat FeedbackEntry[].
                entries={
                  packet?.rounds
                    .find((r) => r.round.id === activeRoundId)
                    ?.feedback_questions?.flatMap((q) => q.feedback_entries ?? []) ?? []
                }
              />
            ) : packetError ? (
              <div className="rounded-[12px] border border-[#FECACA] bg-[#FEF2F2] p-4">
                <p className="font-medium text-[13px] text-[#B91C1C]">
                  Couldn't load this interview's packet.
                </p>
                <p className="mt-1 text-[12px] text-[#B91C1C]/80">{packetError.message}</p>
                {untrackedId && (
                  <p className="mt-2 font-mono text-[11px] text-[#B91C1C]/70">
                    Endpoint: GET /api/v2/untracked-interviews/{untrackedId}/packet
                  </p>
                )}
              </div>
            ) : packetLoading ? (
              <PacketPaneSkeleton id={`${id}-pane-skeleton`} />
            ) : (
              <p className="text-[13px] text-text-muted">Select a round to see evidence.</p>
            )}
          </div>
        </div>
      </aside>
    </div>
  );
}

function RoundRail({
  id,
  reqId,
  candidateId,
  rounds,
  roundsByReq,
  aiByRound,
  activeRoundId,
  viewOnly = false,
  onSelect,
  onRoundRemoved,
}: {
  id: string;
  reqId: string;
  candidateId: string;
  rounds: CandidateRound[];
  roundsByReq: Round[];
  aiByRound: Record<string, boolean>;
  activeRoundId: string | null;
  viewOnly?: boolean;
  onSelect: (roundId: string) => void;
  onRoundRemoved: (roundId: string) => void;
}) {
  const [addOpen, setAddOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const confirm = useConfirm();

  const handleDelete = async (roundId: string) => {
    if (pendingDelete) return;
    setPendingDelete(roundId);
    try {
      await candidateSvc.removeRoundForCandidate(reqId, candidateId, roundId);
      onRoundRemoved(roundId);
    } catch (err) {
      logErr(err);
    } finally {
      setPendingDelete(null);
    }
  };

  return (
    <nav
      id={id}
      aria-label="Rounds"
      className="shrink-0 overflow-x-auto border-border border-b bg-surface/40 px-2 py-2 md:flex md:w-[260px] md:flex-col md:overflow-y-auto md:border-r md:border-b-0 md:px-3 md:py-4 print:hidden"
    >
      <ul className="flex flex-row gap-1 md:flex-col">
        {rounds.map((cr, i) => {
          const roundDef = roundsByReq.find((r) => r.id === cr.round_id);
          const isActive = cr.round_id === activeRoundId;
          const custom = roundDef ? isCustomRound(roundDef) : false;
          const aiHosted = aiByRound[cr.round_id] === true;
          const deleting = pendingDelete === cr.round_id;
          return (
            <li key={cr.id} className="group relative">
              <button
                id={`${id}-round-${cr.round_id}`}
                type="button"
                onClick={() => onSelect(cr.round_id)}
                className={cn(
                  'flex w-full shrink-0 flex-col whitespace-nowrap rounded-[10px] border px-3 py-2 pr-9 text-left transition-colors md:whitespace-normal',
                  custom
                    ? isActive
                      ? 'border-[#F59E0B] bg-[#FFFBEB]'
                      : 'border-transparent bg-[#FFFBEB]/40 hover:border-[#F59E0B] hover:bg-[#FFFBEB]'
                    : isActive
                      ? 'border-text-primary bg-white'
                      : 'border-transparent hover:border-border hover:bg-white',
                )}
              >
                <span className="flex items-center justify-between gap-2">
                  <span
                    className={cn(
                      'flex min-w-0 items-center gap-1.5 truncate font-medium text-[13px]',
                      custom ? 'text-[#B45309]' : 'text-text-primary',
                    )}
                  >
                    {custom && (
                      <Sparkles
                        aria-hidden
                        strokeWidth={1.75}
                        className="h-3 w-3 shrink-0 text-[#B45309]"
                      />
                    )}
                    <span className="truncate">
                      R{i + 1} · {roundDef?.name ?? cr.round_id}
                    </span>
                  </span>
                  {cr.rating && (
                    <span
                      aria-hidden
                      className={cn(
                        'inline-flex shrink-0 items-center rounded-full px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.12em]',
                        RATING_CLS[cr.rating],
                      )}
                    >
                      {cr.rating.replace('_', ' ')}
                    </span>
                  )}
                </span>
                <span className="mt-1 font-mono text-[10px] text-text-faint uppercase tracking-[0.12em]">
                  {custom ? 'Custom · ' : ''}
                  {cr.status}
                  {cr.scheduled_at
                    ? ` · ${formatScheduledDate(cr.scheduled_at, cr.scheduling_timezone)}`
                    : ''}
                </span>
                {aiHosted && (
                  <span
                    id={`${id}-round-${cr.round_id}-ai-badge`}
                    className="mt-1 inline-flex w-fit items-center gap-1 rounded-full border border-cortex-500/30 bg-white px-2 py-0.5 font-medium font-mono text-[9px] text-cortex-500 uppercase tracking-[0.12em]"
                  >
                    <BrandIcon className="h-2.5 w-2.5" />
                    OpenRecruiting takes this round
                  </span>
                )}
              </button>
              {!viewOnly && cr.status !== 'completed' && (
                <button
                  id={`${id}-round-${cr.round_id}-delete`}
                  type="button"
                  aria-label={`Remove ${roundDef?.name ?? 'round'} from this candidate`}
                  disabled={deleting}
                  onClick={async (e) => {
                    e.stopPropagation();
                    const ok = await confirm({
                      title: custom
                        ? `Delete custom round "${roundDef?.name ?? 'this round'}"?`
                        : `Remove "${roundDef?.name ?? 'this round'}" from this candidate?`,
                      body: custom
                        ? 'This removes the custom round for this candidate.'
                        : "The shared plan won't change.",
                      danger: true,
                      confirmLabel: custom ? 'Delete' : 'Remove',
                    });
                    if (ok) void handleDelete(cr.round_id);
                  }}
                  className={cn(
                    'absolute top-1.5 right-1.5 flex h-6 w-6 items-center justify-center rounded-full text-text-muted opacity-0 transition-opacity hover:bg-white hover:text-[#B91C1C] group-hover:opacity-100 focus:opacity-100',
                    deleting && 'cursor-wait opacity-100',
                  )}
                >
                  <Trash2 strokeWidth={1.75} className="h-3.5 w-3.5" />
                </button>
              )}
            </li>
          );
        })}
      </ul>
      {!viewOnly && (
        <button
          id={`${id}-add-round`}
          type="button"
          onClick={() => setAddOpen(true)}
          className="mt-2 inline-flex shrink-0 items-center justify-center gap-1.5 rounded-[10px] border border-border border-dashed bg-white px-3 py-2 font-medium font-sans text-[12.5px] text-text-muted transition-colors hover:border-[#F59E0B] hover:bg-[#FFFBEB] hover:text-[#B45309]"
        >
          <Plus strokeWidth={1.75} className="h-3.5 w-3.5" />
          Add custom round
        </button>
      )}
      {addOpen && !viewOnly && (
        <AddCustomRoundDialog
          id={`${id}-add-form`}
          reqId={reqId}
          candidateId={candidateId}
          onClose={() => setAddOpen(false)}
          onCreated={(roundId) => {
            setAddOpen(false);
            onSelect(roundId);
          }}
        />
      )}
    </nav>
  );
}

interface CriterionDraft {
  key: string;
  heading: string;
  description: string;
}

function makeCriterion(): CriterionDraft {
  return {
    key: `c_${Math.random().toString(36).slice(2, 8)}`,
    heading: '',
    description: '',
  };
}

function AddCustomRoundDialog({
  id,
  reqId,
  candidateId,
  onClose,
  onCreated,
}: {
  id: string;
  reqId: string;
  candidateId: string;
  onClose: () => void;
  onCreated: (roundId: string) => void;
}) {
  const [name, setName] = useState('');
  const [roundType, setRoundType] = useState<RoundType>('technical');
  const [duration, setDuration] = useState<number>(45);
  const [description, setDescription] = useState('');
  const [skillsInput, setSkillsInput] = useState('');
  const [criteria, setCriteria] = useState<CriterionDraft[]>([makeCriterion()]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const parsedSkills = skillsInput
    .split(',')
    .map((s) => s.trim())
    .filter((s) => s.length > 0);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const input: CustomRoundCreateInput = {
        name: name.trim(),
        category: roundType,
        duration_minutes: duration,
        feedback_questions: criteria
          .map((c) => ({ heading: c.heading.trim(), description: c.description.trim() }))
          .filter((c) => c.heading.length > 0),
      };
      const trimmedDescription = description.trim();
      if (trimmedDescription) input.description = trimmedDescription;
      if (parsedSkills.length > 0) input.skills = parsedSkills;
      const { round } = await candidateSvc.addCustomRound(reqId, candidateId, input);
      onCreated(round.id);
    } catch (err) {
      setError(err instanceof ServiceError ? err.message : 'Could not add custom round');
      setBusy(false);
    }
  };

  const updateCriterion = (key: string, patch: Partial<CriterionDraft>) => {
    setCriteria((curr) => curr.map((c) => (c.key === key ? { ...c, ...patch } : c)));
  };
  const removeCriterion = (key: string) => {
    setCriteria((curr) => (curr.length <= 1 ? curr : curr.filter((c) => c.key !== key)));
  };

  return (
    <div
      id={id}
      className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-black/40 p-4 sm:items-center"
      role="dialog"
      aria-modal="true"
    >
      <form
        onSubmit={submit}
        className="my-4 w-full max-w-xl rounded-[16px] border border-border bg-white p-6 shadow-[0_20px_60px_rgba(0,0,0,0.2)]"
      >
        <div className="mb-4 flex items-start justify-between gap-2">
          <div>
            <p className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
              Just for this candidate
            </p>
            <h2 className="mt-1 font-display text-[22px] text-text-primary leading-tight">
              Add custom round
            </h2>
          </div>
          <button
            id={`${id}-close`}
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-full text-text-muted hover:text-text-primary"
          >
            <X strokeWidth={1.75} className="h-4 w-4" />
          </button>
        </div>
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
              Round name
            </span>
            <input
              id={`${id}-name`}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Founder chat"
              className="rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary placeholder:text-text-muted focus:border-text-primary focus:outline-none"
            />
          </label>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1">
              <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
                Type
              </span>
              <select
                id={`${id}-type`}
                value={roundType}
                onChange={(e) => setRoundType(e.target.value as RoundType)}
                className="rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary focus:border-text-primary focus:outline-none"
              >
                <option value="screening">Screening</option>
                <option value="technical">Technical</option>
                <option value="behavioral">Behavioral</option>
                <option value="culture">Culture</option>
                <option value="panel">Panel</option>
                <option value="final">Final</option>
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
                Duration (minutes)
              </span>
              <input
                id={`${id}-duration`}
                type="number"
                min={5}
                max={240}
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value) || 0)}
                className="rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary focus:border-text-primary focus:outline-none"
              />
            </label>
          </div>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
              Description
            </span>
            <textarea
              id={`${id}-description`}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder="What this round is for, what the interviewer should focus on…"
              className="resize-y rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary placeholder:text-text-muted focus:border-text-primary focus:outline-none"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
              Skills
            </span>
            <input
              id={`${id}-skills`}
              value={skillsInput}
              onChange={(e) => setSkillsInput(e.target.value)}
              placeholder="Comma-separated, e.g. system design, leadership, pricing"
              className="rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary placeholder:text-text-muted focus:border-text-primary focus:outline-none"
            />
            {parsedSkills.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1">
                {parsedSkills.map((s, i) => (
                  <span
                    key={`${s}_${i}`}
                    className="inline-flex items-center rounded-full border border-border bg-surface px-2 py-0.5 font-mono text-[10.5px] text-text-secondary uppercase tracking-[0.12em]"
                  >
                    {s}
                  </span>
                ))}
              </div>
            )}
          </label>
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
                Evaluation criteria
              </span>
              <button
                id={`${id}-criteria-add`}
                type="button"
                onClick={() => setCriteria((curr) => [...curr, makeCriterion()])}
                className="inline-flex items-center gap-1 rounded-full border border-border bg-white px-2.5 py-1 font-medium text-[11.5px] text-text-primary hover:border-text-primary"
              >
                <Plus strokeWidth={1.75} className="h-3 w-3" />
                Add criterion
              </button>
            </div>
            <ul className="flex flex-col gap-2">
              {criteria.map((c, i) => (
                <li
                  key={c.key}
                  id={`${id}-criterion-${c.key}`}
                  className="flex items-start gap-2 rounded-[10px] border border-border bg-surface/40 p-2.5"
                >
                  <span
                    aria-hidden
                    className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white font-mono text-[10px] text-text-muted"
                  >
                    {i + 1}
                  </span>
                  <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <input
                      id={`${id}-criterion-${c.key}-heading`}
                      value={c.heading}
                      onChange={(e) => updateCriterion(c.key, { heading: e.target.value })}
                      placeholder="Heading (e.g. Product sense)"
                      className="rounded-[8px] border border-transparent bg-white px-2.5 py-1.5 text-[13px] text-text-primary placeholder:text-text-muted focus:border-text-primary focus:outline-none"
                    />
                    <input
                      id={`${id}-criterion-${c.key}-description`}
                      value={c.description}
                      onChange={(e) => updateCriterion(c.key, { description: e.target.value })}
                      placeholder="What to probe for (optional)"
                      className="rounded-[8px] border border-transparent bg-white px-2.5 py-1.5 text-[12.5px] text-text-muted placeholder:text-text-faint focus:border-text-primary focus:text-text-primary focus:outline-none"
                    />
                  </div>
                  <button
                    id={`${id}-criterion-${c.key}-remove`}
                    type="button"
                    aria-label="Remove criterion"
                    disabled={criteria.length <= 1}
                    onClick={() => removeCriterion(c.key)}
                    className={cn(
                      'mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full transition-colors',
                      criteria.length <= 1
                        ? 'cursor-not-allowed text-text-faint'
                        : 'text-text-muted hover:bg-[#FEF2F2] hover:text-[#B91C1C]',
                    )}
                  >
                    <Trash2 strokeWidth={1.75} className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
        {error && <p className="mt-3 text-[#B91C1C] text-[12.5px]">{error}</p>}
        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            id={`${id}-cancel`}
            type="button"
            onClick={onClose}
            className="rounded-full border border-border bg-white px-3.5 py-2 text-[13px] text-text-primary hover:border-text-primary"
          >
            Cancel
          </button>
          <button
            id={`${id}-submit`}
            type="submit"
            disabled={!name.trim() || duration <= 0 || busy}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full px-3.5 py-2 font-medium text-[13px] transition-colors',
              name.trim() && duration > 0 && !busy
                ? 'border border-[#B45309] bg-[#B45309] text-white hover:bg-[#92400E]'
                : 'cursor-not-allowed border border-border bg-surface text-text-faint',
            )}
          >
            <Sparkles strokeWidth={1.75} className="h-3.5 w-3.5" />
            {busy ? 'Adding…' : 'Add round'}
          </button>
        </div>
      </form>
    </div>
  );
}

function RoundPane({
  id,
  reqId,
  candidateId,
  candidateName,
  roleTitle,
  candidateRound,
  round,
  displayRoundNumber,
  questions,
  entries,
  viewOnly = false,
  aiHosted = false,
}: {
  id: string;
  reqId: string;
  candidateId: string;
  candidateName: string;
  roleTitle: string;
  candidateRound: CandidateRound;
  round: Round;
  displayRoundNumber: number;
  questions: Array<{ id: string; heading: string; description: string }>;
  // Spec §7: feedback entries come from the single /packet response,
  // not a per-round refetch. RoundPane is a pure consumer.
  entries: FeedbackEntry[];
  viewOnly?: boolean;
  // True when round_screening_configs.enabled — OpenRecruiting hosts this round as an
  // async screening call. Scheduling = sending the screening link, not booking.
  aiHosted?: boolean;
}) {
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [requestOpen, setRequestOpen] = useState(false);
  const [paneTab, setPaneTab] = useState<'packet' | 'replay'>('packet');

  // A round that hasn't been scheduled can never have a recording, so the
  // Round replay tab is gated off for it. The pane tab persists as the user
  // switches rounds in the rail — if they land on a gated round while the
  // replay pane is open, fall back to the packet pane rather than stranding
  // them on a disabled tab.
  const replayGated = candidateRound.status === 'pending';
  useEffect(() => {
    if (replayGated && paneTab === 'replay') setPaneTab('packet');
  }, [replayGated, paneTab]);

  return (
    <div id={id} className="flex flex-col gap-4">
      <PrintPortal>
        <PrintableRoundPacket
          candidateName={candidateName}
          roleTitle={roleTitle}
          round={round}
          candidateRound={candidateRound}
          entries={entries}
          questionSummaries={candidateRound.question_summaries}
        />
      </PrintPortal>

      <InterviewContextCard
        id={`${id}-context`}
        candidateRound={candidateRound}
        round={round}
        displayRoundNumber={displayRoundNumber}
        entries={entries}
        viewOnly={viewOnly}
        aiHosted={aiHosted}
        onSchedule={() => setScheduleOpen(true)}
        onCancel={async () => {
          await interviews
            .cancel(reqId, candidateId, candidateRound.round_id, {
              crId: candidateRound.id,
            })
            .catch(logErr);
        }}
        onRequestFeedback={() => setRequestOpen(true)}
        onDownloadPdf={() => {
          if (typeof window !== 'undefined') window.print();
        }}
      />

      <div
        id={`${id}-tabs`}
        role="tablist"
        className="flex gap-1 rounded-[12px] bg-surface p-1 print:hidden"
      >
        <PaneTabButton
          id={`${id}-tab-packet`}
          label="Feedback packet"
          active={paneTab === 'packet'}
          onClick={() => setPaneTab('packet')}
        />
        <PaneTabButton
          id={`${id}-tab-replay`}
          label="Round replay"
          active={paneTab === 'replay'}
          disabled={replayGated}
          title={replayGated ? 'Available once this round is scheduled' : undefined}
          onClick={() => setPaneTab('replay')}
        />
      </div>

      <div className={cn('flex flex-col gap-4', paneTab !== 'packet' && 'hidden print:flex')}>
        {candidateRound.summary && (
          <RoundSummaryCard
            id={`${id}-summary`}
            summary={candidateRound.summary}
            rating={candidateRound.rating}
          />
        )}

        {candidateRound.authenticity_signals && (
          <AuthenticityPanel
            id={`${id}-authenticity`}
            signals={candidateRound.authenticity_signals}
          />
        )}

        <EvaluationCriteria
          id={`${id}-evaluation`}
          questions={questions}
          entries={entries}
          questionSummaries={candidateRound.question_summaries}
        />
      </div>

      {paneTab === 'replay' && !replayGated && (
        <div className="print:hidden">
          {/* Spec §7: recording URL + transcript are lazy fetches gated on
              the Replay tab being open. The full RoundRecording (URL +
              segments) is loaded here on demand, not at drawer mount. */}
          <RecordingSection
            id={`${id}-recording`}
            candidateRoundId={candidateRound.id}
            status={candidateRound.status}
          />
        </div>
      )}

      {scheduleOpen && (
        <ScheduleModal
          id={`${id}-schedule`}
          reqId={reqId}
          candidateId={candidateId}
          roundId={candidateRound.round_id}
          existing={candidateRound}
          aiHosted={aiHosted}
          onClose={() => setScheduleOpen(false)}
        />
      )}
      {requestOpen && (
        <FeedbackRequestModal
          id={`${id}-request`}
          reqId={reqId}
          candidateId={candidateId}
          roundId={candidateRound.round_id}
          defaultEmail={candidateRound.interviewer_email ?? ''}
          onClose={() => setRequestOpen(false)}
        />
      )}
    </div>
  );
}

const STATUS_CONTEXT_STYLE: Record<
  CandidateRound['status'],
  { border: string; bg: string; text: string; dot: string; label: string }
> = {
  pending: {
    border: 'border-border',
    bg: 'bg-surface',
    text: 'text-text-muted',
    dot: 'bg-text-faint',
    label: 'Not scheduled',
  },
  scheduled: {
    border: 'border-[#BFDBFE]',
    bg: 'bg-[#EFF6FF]',
    text: 'text-[#1D4ED8]',
    dot: 'bg-[#1D4ED8]',
    label: 'Scheduled',
  },
  in_progress: {
    border: 'border-[#BFDBFE]',
    bg: 'bg-[#EFF6FF]',
    text: 'text-[#1D4ED8]',
    dot: 'bg-[#1D4ED8]',
    label: 'In progress',
  },
  completed: {
    border: 'border-[#A7F3D0]',
    bg: 'bg-[#ECFDF5]',
    text: 'text-[#047857]',
    dot: 'bg-[#059669]',
    label: 'Completed',
  },
  cancelled: {
    border: 'border-[#FECACA]',
    bg: 'bg-[#FEF2F2]',
    text: 'text-[#B91C1C]',
    dot: 'bg-[#B91C1C]',
    label: 'Cancelled',
  },
};

function initialsFromName(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('');
}

function InterviewContextCard({
  id,
  candidateRound,
  round,
  displayRoundNumber,
  entries,
  viewOnly = false,
  aiHosted = false,
  onSchedule,
  onCancel,
  onRequestFeedback,
  onDownloadPdf,
}: {
  id: string;
  candidateRound: CandidateRound;
  round: Round;
  displayRoundNumber: number;
  entries: FeedbackEntry[];
  viewOnly?: boolean;
  aiHosted?: boolean;
  onSchedule: () => void;
  onCancel: () => void;
  onRequestFeedback: () => void;
  onDownloadPdf: () => void;
}) {
  const status = STATUS_CONTEXT_STYLE[candidateRound.status];
  const isCompletedWithVerdict =
    candidateRound.status === 'completed' && candidateRound.rating != null;
  const chipLabel = isCompletedWithVerdict ? RATING_LABEL[candidateRound.rating!] : status.label;
  const chipCls = isCompletedWithVerdict
    ? RATING_CLS[candidateRound.rating!]
    : `${status.border} ${status.bg} ${status.text}`;
  const dateLabel = candidateRound.scheduled_at
    ? formatScheduledDate(
        candidateRound.scheduled_at,
        candidateRound.scheduling_timezone,
        'EEE, MMM d',
      )
    : null;
  const timeLabel = candidateRound.scheduled_at
    ? formatScheduledTime(candidateRound.scheduled_at, candidateRound.scheduling_timezone)
    : null;
  const duration = round.duration_minutes ?? null;
  // A AI-hosted round has no human interviewer — OpenRecruiting's screening agent
  // runs it. Show that explicitly instead of "Unassigned / No email yet".
  const interviewer = aiHosted
    ? 'OpenRecruiting Screening Agent'
    : (candidateRound.interviewer_name ?? null);
  const interviewerSecondary = aiHosted
    ? 'Hosted by OpenRecruiting'
    : (candidateRound.interviewer_email ?? 'No email yet');
  const interviewerInitials = aiHosted
    ? null
    : interviewer
      ? initialsFromName(interviewer)
      : '·';
  const questionCount = (round.feedback_questions ?? []).length;
  // "Scorecard X / Y" = questions answered / total questions. Count DISTINCT
  // questions with at least one submitted entry — the feedback agent extracts
  // several evidence points per question, so a raw entry count overshoots the
  // question total (the confusing "7 / 3"). Scoping to the round's own question
  // ids also guards against entries left over from since-removed questions.
  const answeredQuestionIds = new Set(
    entries.filter((e) => e.created_at).map((e) => e.feedback_question_id),
  );
  const questionsAnswered = (round.feedback_questions ?? []).filter((q) =>
    answeredQuestionIds.has(q.id),
  ).length;

  return (
    <article
      id={id}
      className="overflow-hidden rounded-[16px] border border-border bg-white shadow-[0_1px_2px_rgba(0,0,0,0.02)] print:break-inside-avoid print:shadow-none"
    >
      <header className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4">
        <div className="min-w-0">
          <div className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]">
            Round {displayRoundNumber} · {aiHosted ? 'OpenRecruiting screening' : 'Interview'}
          </div>
          <h3 className="mt-1 font-display text-[22px] text-text-primary leading-tight tracking-[-0.01em]">
            {round.name}
          </h3>
          {aiHosted && (
            <span
              id={`${id}-ai-badge`}
              className="mt-2 inline-flex items-center gap-1 rounded-full border border-cortex-500/30 bg-white px-2 py-0.5 font-medium font-mono text-[10px] text-cortex-500 uppercase tracking-[0.14em]"
            >
              <BrandIcon className="h-2.5 w-2.5" />
              OpenRecruiting takes this round
            </span>
          )}
        </div>
        {!viewOnly && (
          <div className="flex items-center gap-2 print:hidden">
            {candidateRound.status === 'completed' && (
              <button
                id={`${id}-download`}
                type="button"
                onClick={onDownloadPdf}
                className="inline-flex items-center gap-1.5 rounded-full border border-border bg-white px-3 py-1.5 font-medium font-sans text-[12px] text-text-primary hover:border-text-primary cursor-pointer"
              >
                <Download strokeWidth={1.75} className="h-3.5 w-3.5" />
                PDF
              </button>
            )}
            <button
              id={`${id}-schedule`}
              type="button"
              onClick={onSchedule}
              disabled={candidateRound.status === 'completed'}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 font-medium font-sans text-[12px] transition-colors',
                candidateRound.status === 'completed'
                  ? 'cursor-not-allowed border-border bg-surface text-text-faint'
                  : 'border-text-primary bg-text-primary text-white hover:bg-[#222]',
              )}
            >
              {aiHosted ? (
                <BrandIcon className="h-3.5 w-3.5" />
              ) : (
                <Calendar strokeWidth={1.75} className="h-3.5 w-3.5" />
              )}
              {aiHosted
                ? candidateRound.status === 'scheduled'
                  ? 'Re-send link'
                  : 'Send screening link'
                : candidateRound.status === 'scheduled'
                  ? 'Reschedule'
                  : 'Schedule'}
            </button>
            {candidateRound.status === 'scheduled' && (
              <button
                id={`${id}-cancel`}
                type="button"
                onClick={onCancel}
                className="rounded-full border border-border bg-white px-3 py-1.5 font-medium font-sans text-[12px] text-text-muted hover:border-[#B91C1C] hover:text-[#B91C1C]"
              >
                Cancel
              </button>
            )}
          </div>
        )}
      </header>

      <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-3 pb-1">
        <span
          className={cn(
            'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-medium font-sans text-[11.5px]',
            isCompletedWithVerdict ? chipCls : cn('border', status.border, status.bg, status.text),
          )}
        >
          {!isCompletedWithVerdict && (
            <span aria-hidden className={cn('h-1.5 w-1.5 rounded-full', status.dot)} />
          )}
          {chipLabel}
        </span>
        {candidateRound.status === 'completed' && candidateRound.feedback_approved_at && (
          <span
            id={`${id}-approved`}
            className="inline-flex items-center gap-1.5 rounded-full border border-[#A7F3D0] bg-[#ECFDF5] px-2.5 py-0.5 font-medium font-mono text-[10.5px] text-[#047857] uppercase tracking-[0.14em]"
            title={
              candidateRound.feedback_approved_by_email
                ? `Approved by ${candidateRound.feedback_approved_by_email} on ${new Date(candidateRound.feedback_approved_at).toLocaleDateString()}`
                : `Approved on ${new Date(candidateRound.feedback_approved_at).toLocaleDateString()}`
            }
          >
            <CheckCircle2 strokeWidth={2} className="h-3 w-3" />
            Approved by interviewer
          </span>
        )}
        {candidateRound.status === 'completed' &&
          !candidateRound.feedback_approved_at &&
          questionsAnswered === 0 &&
          !viewOnly && (
            <button
              id={`${id}-request`}
              type="button"
              onClick={onRequestFeedback}
              className="inline-flex items-center gap-1.5 rounded-full border border-text-primary bg-text-primary px-3 py-1 font-medium font-sans text-[11.5px] text-white hover:bg-[#222] print:hidden cursor-pointer"
            >
              <Mail strokeWidth={1.75} className="h-3 w-3" />
              Request feedback
            </button>
          )}
      </div>

      <div className="grid gap-4 px-5 py-4 sm:grid-cols-2 lg:grid-cols-4">
        <ContextStat
          id={`${id}-when`}
          label="When"
          icon={<Calendar strokeWidth={1.75} className="h-3.5 w-3.5" />}
          primary={aiHosted ? 'Async' : (dateLabel ?? 'Not set')}
          secondary={aiHosted ? 'Candidate completes anytime' : (timeLabel ?? 'Pick a time')}
        />
        {candidateRound.status !== 'completed' && (
          <ContextStat
            id={`${id}-dur`}
            label="Duration"
            icon={<Mic strokeWidth={1.75} className="h-3.5 w-3.5" />}
            primary={duration ? `${duration} min` : '—'}
            secondary="Planned for this round"
          />
        )}
        <ContextStat
          id={`${id}-interviewer`}
          label="Interviewer"
          icon={<Users strokeWidth={1.75} className="h-3.5 w-3.5" />}
          primary={interviewer ?? 'Unassigned'}
          secondary={interviewerSecondary}
          leading={
            aiHosted ? (
              <span
                aria-hidden
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-cortex-500/30 bg-white text-cortex-500"
              >
                <BrandIcon className="h-3.5 w-3.5" />
              </span>
            ) : (
              <span
                aria-hidden
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface font-medium font-mono text-[10px] text-text-primary"
              >
                {interviewerInitials}
              </span>
            )
          }
        />
        <ContextStat
          id={`${id}-scorecard`}
          label="Scorecard"
          icon={<ClipboardList strokeWidth={1.75} className="h-3.5 w-3.5" />}
          primary={`${questionsAnswered} / ${questionCount}`}
          secondary={
            questionsAnswered === 0
              ? 'Not submitted'
              : questionsAnswered === questionCount
                ? 'All questions answered'
                : 'Partial scorecard'
          }
        />
      </div>

      {/* Round description + skills intentionally omitted: that plan-level info
          lives in the interview plan, and showing it only for not-yet-completed
          rounds made the drawer header inconsistent across rounds. The packet
          drawer shows interview context + scorecard only. */}
    </article>
  );
}

function ContextStat({
  id,
  label,
  icon,
  primary,
  secondary,
  leading,
}: {
  id: string;
  label: string;
  icon: React.ReactNode;
  primary: string;
  secondary: string;
  leading?: React.ReactNode;
}) {
  return (
    <div id={id} className="flex items-center gap-3 min-w-0">
      {leading ?? (
        <span
          aria-hidden
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface text-text-muted"
        >
          {icon}
        </span>
      )}
      <div className="min-w-0">
        <div className="font-mono text-[9.5px] text-text-faint uppercase tracking-[0.14em]">
          {label}
        </div>
        <div className="mt-0.5 truncate font-medium font-sans text-[13px] text-text-primary">
          {primary}
        </div>
        <div className="truncate text-[11.5px] text-text-muted">{secondary}</div>
      </div>
    </div>
  );
}

function RoundSummaryCard({
  id,
  summary,
  rating,
}: {
  id: string;
  summary: string;
  rating: RoundRating | null;
}) {
  return (
    <section
      id={id}
      className="rounded-[16px] border border-border bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)] print:break-inside-avoid print:shadow-none"
    >
      <header className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span
            aria-hidden
            className="flex h-6 w-6 items-center justify-center rounded-full bg-surface text-text-muted"
          >
            <FileText strokeWidth={1.75} className="h-3.5 w-3.5" />
          </span>
          <h3 className="font-display text-[20px] text-text-primary leading-tight tracking-[-0.005em]">
            Round summary
          </h3>
        </div>
        {rating && (
          <div id={`${id}-verdict`} className="flex flex-col items-end gap-1">
            <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.18em]">
              Round verdict
            </span>
            <span
              className={cn(
                'inline-flex items-center rounded-[6px] border px-2.5 py-1 font-semibold font-sans text-[12.5px] uppercase tracking-[0.06em]',
                ROLLUP_CHIP_STYLE[ratingToVerdictBucket(rating)],
              )}
            >
              {RATING_LABEL[rating]}
            </span>
          </div>
        )}
      </header>
      <p className="whitespace-pre-wrap text-[13.5px] text-text-secondary leading-[1.6]">
        {summary}
      </p>
    </section>
  );
}

function ratingToVerdictBucket(rating: RoundRating): EvidenceStatus {
  if (rating === 'strong_yes' || rating === 'yes') return 'verified';
  if (rating === 'maybe') return 'partial';
  return 'contradicted';
}

function EvaluationCriteria({
  id,
  questions,
  entries,
  questionSummaries,
}: {
  id: string;
  questions: Array<{ id: string; heading: string; description: string }>;
  entries: FeedbackEntry[];
  questionSummaries: Record<string, string>;
}) {
  const pointsByQuestion = useMemo(() => {
    const m = new Map<string, FeedbackEntry[]>();
    entries.forEach((e) => {
      const arr = m.get(e.feedback_question_id) ?? [];
      arr.push(e);
      m.set(e.feedback_question_id, arr);
    });
    return m;
  }, [entries]);

  // Default-expand every question that has at least one feedback point so the
  // recruiter sees the evidence on open (matches v1 hiring-packet behavior).
  // Questions with no evidence stay collapsed (their "Feedback not captured
  // yet" message renders independently of expanded state).
  const [openQuestions, setOpenQuestions] = useState<Set<string>>(
    () => new Set(entries.map((e) => e.feedback_question_id)),
  );
  // Re-sync when entries change (e.g., active round switches in the rail).
  useEffect(() => {
    setOpenQuestions(new Set(entries.map((e) => e.feedback_question_id)));
  }, [entries]);
  const toggleQuestion = (qid: string) => {
    setOpenQuestions((prev) => {
      const next = new Set(prev);
      if (next.has(qid)) next.delete(qid);
      else next.add(qid);
      return next;
    });
  };

  if (questions.length === 0) {
    return (
      <section
        id={id}
        className="rounded-[16px] border border-border border-dashed bg-white p-6 text-center text-[13px] text-text-muted"
      >
        This round has no feedback questions yet — edit the plan to add some.
      </section>
    );
  }

  return (
    <section
      id={id}
      className="rounded-[16px] border border-border bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)] print:shadow-none"
    >
      <header className="mb-4 flex items-center gap-2">
        <span
          aria-hidden
          className="flex h-6 w-6 items-center justify-center rounded-full bg-surface text-text-muted"
        >
          <ClipboardList strokeWidth={1.75} className="h-3.5 w-3.5" />
        </span>
        <h3 className="font-display text-[20px] text-text-primary leading-tight tracking-[-0.005em]">
          Evaluation criteria
        </h3>
      </header>

      <ol id={`${id}-list`} className="flex flex-col gap-3">
        {questions.map((q, i) => {
          // candidate_rounds.question_summaries JSONB is keyed by
          // question_number-as-string (e.g. {"1": "...", "2": "..."}) per the
          // feedback Lambda contract, NOT by feedback_question.id. Look up by
          // both keys for forward-compatibility, but the canonical key is the
          // 1-indexed position (matches the rendered "1.", "2." labels).
          const positionKey = String(i + 1);
          const summary = questionSummaries[positionKey] ?? questionSummaries[q.id] ?? null;
          return (
            <li key={q.id}>
              <QuestionCard
                id={`${id}-q-${i + 1}`}
                questionNumber={i + 1}
                heading={q.heading}
                description={q.description}
                points={pointsByQuestion.get(q.id) ?? []}
                questionSummary={summary}
                expanded={openQuestions.has(q.id)}
                onToggle={() => toggleQuestion(q.id)}
              />
            </li>
          );
        })}
      </ol>
    </section>
  );
}

const ROLLUP_CHIP_LABEL: Record<EvidenceStatus, string> = {
  supported: 'supported',
  verified: 'supported',
  partial: 'partially supported',
  contradicted: 'contradicted',
  none: 'not supported',
};

const ROLLUP_CHIP_STYLE: Record<EvidenceStatus, string> = {
  supported: 'border-[#A7F3D0] bg-[#ECFDF5] text-[#047857]',
  verified: 'border-[#A7F3D0] bg-[#ECFDF5] text-[#047857]',
  partial: 'border-[#FDE68A] bg-[#FFFBEB] text-[#B45309]',
  contradicted: 'border-[#FECACA] bg-[#FEF2F2] text-[#B91C1C]',
  none: 'border-[#FDE68A] bg-[#FFFBEB] text-[#B45309]',
};

function rollupChipIcon(status: EvidenceStatus) {
  if (status === 'supported' || status === 'verified')
    return <CheckCircle2 strokeWidth={2} className="h-3.5 w-3.5" />;
  if (status === 'contradicted') return <XCircle strokeWidth={2} className="h-3.5 w-3.5" />;
  return <AlertTriangle strokeWidth={2} className="h-3.5 w-3.5" />;
}

function QuestionCard({
  id,
  questionNumber,
  heading,
  description,
  points,
  questionSummary,
  expanded,
  onToggle,
}: {
  id: string;
  questionNumber: number;
  heading: string;
  description: string;
  points: FeedbackEntry[];
  questionSummary: string | null;
  expanded: boolean;
  onToggle: () => void;
}) {
  const counts = points.reduce(
    (acc, p) => {
      acc[p.evidence_status] = (acc[p.evidence_status] ?? 0) + 1;
      return acc;
    },
    {} as Record<EvidenceStatus, number>,
  );
  // `'supported'` is what the feedback Lambda writes today (per the
  // candidate_feedback CHECK enum). Older specs called this `'verified'`,
  // which still lives in the type for back-compat — both are rendered as
  // positive signals via ROLLUP_CHIP_LABEL.
  const orderedStatuses: EvidenceStatus[] = [
    'supported',
    'verified',
    'partial',
    'contradicted',
    'none',
  ];
  const visibleChips = orderedStatuses.filter((s) => (counts[s] ?? 0) > 0);
  const hasPoints = points.length > 0;

  return (
    <article
      id={id}
      className="rounded-[12px] border border-border bg-surface/40 p-4 print:break-inside-avoid"
    >
      <header>
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-[12px] text-text-secondary tabular-nums">
            {questionNumber}.
          </span>
          <p className="font-semibold text-[14px] text-text-primary leading-snug">{heading}</p>
        </div>
        {description && (
          <p className="mt-1 text-[12.5px] text-text-muted leading-[1.5]">{description}</p>
        )}
      </header>

      {questionSummary && (
        <div
          id={`${id}-summary`}
          className="mt-3 rounded-[10px] border border-border bg-white px-4 py-3"
        >
          <p className="text-[13px] text-text-primary leading-[1.6]">{questionSummary}</p>
        </div>
      )}

      {hasPoints && (
        <button
          id={`${id}-rollup`}
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          className="mt-3 flex w-full items-center justify-between gap-2 rounded-[10px] border border-border bg-white px-4 py-2.5 text-left transition-colors hover:border-text-primary"
        >
          <span className="flex flex-wrap items-center gap-2">
            {visibleChips.map((s) => {
              const n = counts[s] ?? 0;
              const Icon = ROLLUP_ICON[s];
              return (
                <span
                  key={s}
                  className={cn(
                    'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-medium font-sans text-[11.5px]',
                    ROLLUP_CHIP_STYLE[s],
                  )}
                  title={`${n} ${ROLLUP_CHIP_LABEL[s]}`}
                >
                  <Icon strokeWidth={1.75} className="h-3 w-3" />
                  <span className="tabular-nums">{n}</span>
                </span>
              );
            })}
          </span>
          <ChevronDown
            strokeWidth={1.75}
            className={cn(
              'h-4 w-4 shrink-0 text-text-muted transition-transform print:hidden',
              expanded && 'rotate-180',
            )}
          />
        </button>
      )}

      {!hasPoints && (
        <p className="mt-3 text-[12px] text-text-faint italic">
          Feedback not captured yet — voice agent will collect it after the interviewer leaves.
        </p>
      )}

      {expanded && hasPoints && (
        <ol id={`${id}-points`} className="mt-3 flex flex-col gap-2 print:hidden">
          {points.map((p, pIdx) => (
            <li
              key={p.id}
              id={`${id}-p-${pIdx + 1}`}
              className="rounded-[10px] border border-border bg-white px-4 py-3"
            >
              <div className="flex items-start gap-2.5">
                <span
                  className={cn(
                    'mt-0.5 inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 font-medium font-sans text-[10.5px]',
                    ROLLUP_CHIP_STYLE[p.evidence_status],
                  )}
                >
                  {rollupChipIcon(p.evidence_status)}
                  {ROLLUP_CHIP_LABEL[p.evidence_status]}
                </span>
                <p className="flex-1 text-[12.5px] text-text-secondary leading-[1.6]">
                  {p.feedback_text}
                </p>
              </div>
              {p.evidence.length > 0 && (
                <ul className="mt-2 flex flex-col gap-1 border-border border-l-2 pl-3">
                  {p.evidence.map((quote) => (
                    <li
                      key={quote}
                      className="text-[12px] text-text-secondary italic leading-[1.55]"
                    >
                      {quote}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ol>
      )}
    </article>
  );
}

function PaneTabButton({
  id,
  label,
  active,
  onClick,
  disabled = false,
  title,
}: {
  id: string;
  label: string;
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
  title?: string | undefined;
}) {
  return (
    <button
      id={id}
      type="button"
      role="tab"
      aria-selected={active}
      disabled={disabled}
      title={title}
      onClick={onClick}
      className={cn(
        'flex flex-1 shrink-0 items-center justify-center whitespace-nowrap rounded-[10px] px-3 py-1.5 font-medium font-sans text-[12.5px] transition-colors',
        disabled
          ? 'cursor-not-allowed text-text-faint'
          : active
            ? 'bg-white text-text-primary shadow-[0_1px_3px_rgba(0,0,0,0.04)]'
            : 'text-text-muted hover:text-text-primary',
      )}
    >
      {label}
    </button>
  );
}

function formatClock(secs: number): string {
  const s = Math.max(0, Math.floor(secs));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, '0')}`;
}

function RecordingSection({
  id,
  candidateRoundId,
  status,
}: {
  id: string;
  candidateRoundId: string;
  status: CandidateRound['status'];
}) {
  // Spec §7: lazy — only fires when the Replay tab renders this component.
  // The full RoundRecording (URL + transcript segments) is fetched here
  // because the packet provides only metadata (status/duration/has_transcript).
  const { data: recording } = useRecording(candidateRoundId);
  const available = !!recording?.available;

  // All hooks must run on every render in the same order — declare them BEFORE
  // any early return below. Previously the unavailable-recording case returned
  // before the useState/useEffect/useMemo block, which triggered React's
  // "change in the order of Hooks" runtime error the first time data arrived.
  const totalDuration = recording?.duration_seconds ?? 0;
  const fbStart = recording?.feedback_start_seconds ?? null;
  const hasFeedbackPortion = fbStart !== null && fbStart < totalDuration;

  const [segment, setSegment] = useState<'interview' | 'feedback'>('interview');
  const [elapsed, setElapsed] = useState(0);
  const [playing, setPlaying] = useState(false);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const range = useMemo(() => {
    if (!hasFeedbackPortion || fbStart === null) {
      return { start: 0, end: totalDuration };
    }
    return segment === 'interview'
      ? { start: 0, end: fbStart }
      : { start: fbStart, end: totalDuration };
  }, [segment, hasFeedbackPortion, fbStart, totalDuration]);

  // Clamp elapsed when switching segments.
  useEffect(() => {
    setElapsed((t) => {
      if (t < range.start || t > range.end) return range.start;
      return t;
    });
    setPlaying(false);
  }, [range.start, range.end]);

  const transcriptSegments = recording?.transcript_segments ?? [];
  // Show ALL transcript segments regardless of which segment tab is active.
  // Previous behavior filtered by [range.start, range.end), but Recall's
  // feedback_start_seconds boundary often doesn't align with where the
  // candidate actually starts speaking — for short interviews the entire
  // transcript can sit in the "feedback" half, leaving the Interview tab
  // empty and confusing the recruiter into thinking we lost the transcript.
  // The segment tabs still control video playhead and the highlight below.
  const visibleSegments = transcriptSegments;

  const activeSegmentIndex = useMemo(() => {
    return visibleSegments.findIndex((s) => elapsed >= s.start_seconds && elapsed < s.end_seconds);
  }, [visibleSegments, elapsed]);

  if (!available || !recording) {
    // A recording is only still "on its way" while the round is scheduled or
    // actively recording. For any other state (e.g. completed with no capture)
    // show a settled "no recording" message instead of a perpetual spinner
    // that implies one is coming.
    const recordingExpected = status === 'scheduled' || status === 'in_progress';
    return (
      <section id={id} className="rounded-[16px] border border-border border-dashed bg-white p-6">
        <header className="flex items-center gap-2">
          <span
            aria-hidden
            className="flex h-6 w-6 items-center justify-center rounded-full bg-surface text-text-muted"
          >
            <Video strokeWidth={1.75} className="h-3.5 w-3.5" />
          </span>
          <h3 className="font-display text-[20px] text-text-primary leading-tight tracking-[-0.005em]">
            Round replay
          </h3>
          <span className="ml-auto font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
            {recordingExpected ? 'Not yet available' : 'No recording'}
          </span>
        </header>
        <div className="mt-3 flex items-center gap-2 text-[12.5px] text-text-muted">
          {recordingExpected ? (
            <>
              <span
                aria-hidden
                className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-text-muted/30 border-t-text-primary"
              />
              Recording will appear here once it's ready.
            </>
          ) : (
            <>No recording is available for this round.</>
          )}
        </div>
      </section>
    );
  }

  return (
    <section
      id={id}
      className="overflow-hidden rounded-[16px] border border-border bg-white shadow-[0_1px_2px_rgba(0,0,0,0.02)]"
    >
      <header className="flex flex-wrap items-center justify-between gap-2 border-border border-b px-5 py-3">
        <div className="flex items-center gap-2">
          <span
            aria-hidden
            className="flex h-6 w-6 items-center justify-center rounded-full bg-surface text-text-muted"
          >
            <Video strokeWidth={1.75} className="h-3.5 w-3.5" />
          </span>
          <h3 className="font-display text-[20px] text-text-primary leading-tight tracking-[-0.005em]">
            Round replay
          </h3>
          <span className="inline-flex items-center gap-1 rounded-full border border-[#FECACA] bg-[#FEF2F2] px-2 py-0.5 font-mono text-[9.5px] text-[#B91C1C] uppercase tracking-[0.14em]">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#B91C1C]" /> REC
          </span>
        </div>
        <button
          id={`${id}-fullscreen`}
          type="button"
          onClick={() => {
            const el = stageRef.current;
            if (!el) return;
            if (document.fullscreenElement === el) {
              void document.exitFullscreen();
            } else {
              void el.requestFullscreen?.();
            }
          }}
          className="inline-flex items-center gap-1.5 rounded-full border border-border bg-white px-3 py-1.5 font-medium text-[11.5px] text-text-primary hover:border-text-primary"
        >
          <Maximize2 strokeWidth={1.75} className="h-3.5 w-3.5" />
          Fullscreen
        </button>
      </header>

      {hasFeedbackPortion && (
        <div
          id={`${id}-segments`}
          role="tablist"
          aria-label="Recording segment"
          className="flex gap-2 border-border border-b bg-surface/40 px-4 py-3"
        >
          <SegmentTab
            id={`${id}-segment-interview`}
            label="Interview"
            sublabel={`${formatClock(0)}–${formatClock(fbStart)}`}
            active={segment === 'interview'}
            onClick={() => setSegment('interview')}
          />
          <SegmentTab
            id={`${id}-segment-feedback`}
            label="Feedback"
            sublabel={`${formatClock(fbStart)}–${formatClock(totalDuration)}`}
            active={segment === 'feedback'}
            onClick={() => setSegment('feedback')}
          />
        </div>
      )}

      <div id={`${id}-body`} className="grid gap-0 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <VideoPlayer
          id={`${id}-player`}
          stageRef={stageRef}
          videoRef={videoRef}
          recordingUrl={recording.recording_url ?? ''}
          rangeStart={range.start}
          rangeEnd={range.end}
          elapsed={elapsed}
          playing={playing}
          onElapsedChange={setElapsed}
          onPlayingChange={setPlaying}
        />
        <TranscriptViewer
          id={`${id}-transcript`}
          segments={visibleSegments}
          activeIndex={activeSegmentIndex}
          onSeek={(t) => {
            const el = videoRef.current;
            if (el) {
              el.currentTime = t;
              void el.play();
            }
            setElapsed(t);
          }}
        />
      </div>
    </section>
  );
}

function SegmentTab({
  id,
  label,
  sublabel,
  active,
  onClick,
}: {
  id: string;
  label: string;
  sublabel: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      id={id}
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        'flex flex-1 flex-col items-start gap-0.5 rounded-[10px] px-4 py-2.5 transition-colors cursor-pointer',
        active
          ? 'bg-white text-text-primary shadow-[0_1px_3px_rgba(0,0,0,0.05)]'
          : 'text-text-muted hover:bg-white/60 hover:text-text-primary',
      )}
    >
      <span className="font-medium font-sans text-[13px]">{label}</span>
      <span className="font-mono text-[10px] text-text-faint tabular-nums">{sublabel}</span>
    </button>
  );
}

export function TranscriptViewer({
  id,
  segments,
  activeIndex,
  onSeek,
}: {
  id: string;
  segments: TranscriptSegment[];
  activeIndex: number;
  onSeek: (seconds: number) => void;
}) {
  if (segments.length === 0) {
    return (
      <aside
        id={id}
        className="flex min-h-[280px] items-center justify-center border-border border-l bg-surface/30 px-4 py-4 text-[12.5px] text-text-muted"
      >
        No transcript available for this segment.
      </aside>
    );
  }
  return (
    <aside
      id={id}
      className="flex max-h-[480px] min-h-[280px] flex-col border-border border-l bg-white"
    >
      <header className="flex items-center gap-2 border-border border-b px-4 py-2.5 font-mono text-[10px] text-text-faint uppercase tracking-[0.18em]">
        <Radio strokeWidth={1.75} className="h-3 w-3" />
        Transcript
      </header>
      <ol id={`${id}-list`} className="flex-1 overflow-y-auto divide-y divide-border">
        {segments.map((seg, i) => {
          const isActive = i === activeIndex;
          return (
            <li key={`${seg.start_seconds}-${i}`}>
              <button
                type="button"
                onClick={() => onSeek(seg.start_seconds)}
                aria-current={isActive ? 'true' : undefined}
                className={cn(
                  'flex w-full flex-col gap-1 px-4 py-2.5 text-left transition-colors hover:bg-surface/60',
                  isActive && 'bg-[#FEF3C7]/40',
                )}
              >
                <div className="flex items-center justify-between gap-2 text-[10.5px] text-text-faint">
                  <span className="font-medium font-mono uppercase tracking-[0.12em]">
                    {seg.speaker}
                  </span>
                  <span className="font-mono tabular-nums">{formatClock(seg.start_seconds)}</span>
                </div>
                <p
                  className={cn(
                    'text-[12.5px] leading-[1.55]',
                    isActive ? 'text-text-primary' : 'text-text-secondary',
                  )}
                >
                  {seg.text}
                </p>
              </button>
            </li>
          );
        })}
      </ol>
    </aside>
  );
}

function VideoPlayer({
  id,
  stageRef,
  videoRef,
  recordingUrl,
  rangeStart,
  rangeEnd,
  elapsed,
  playing,
  onElapsedChange,
  onPlayingChange,
}: {
  id: string;
  stageRef: React.MutableRefObject<HTMLDivElement | null>;
  videoRef: React.MutableRefObject<HTMLVideoElement | null>;
  recordingUrl: string;
  rangeStart: number;
  rangeEnd: number;
  elapsed: number;
  playing: boolean;
  onElapsedChange: (t: number) => void;
  onPlayingChange: (p: boolean) => void;
}) {
  const hasUrl = recordingUrl.length > 0 && recordingUrl !== `#recording/${recordingUrl}`;

  // Sync play/pause to the underlying <video>.
  useEffect(() => {
    const el = videoRef.current;
    if (!el) return;
    if (playing) {
      void el.play().catch(() => {
        onPlayingChange(false);
      });
    } else {
      el.pause();
    }
  }, [playing, onPlayingChange]);

  // Seek the underlying <video> when the user toggles between Interview /
  // Feedback segments — but DO NOT cap playback at rangeEnd. The segment
  // toggle is a "scroll to" affordance, not a playback cage; the user can
  // scrub freely through the whole recording with the native controls.
  // Tracks rangeStart in a ref so this effect only fires when the user
  // actually flips segments (rangeStart changes), not on every timeupdate.
  const lastRangeStartRef = useRef<number | null>(null);
  useEffect(() => {
    const el = videoRef.current;
    if (!el) return;
    if (lastRangeStartRef.current === rangeStart) return;
    lastRangeStartRef.current = rangeStart;
    // Only re-seek when the new segment doesn't already contain currentTime.
    // Avoids yanking the user back when they manually scrubbed past it.
    if (el.currentTime < rangeStart || el.currentTime > rangeEnd) {
      el.currentTime = rangeStart;
    }
  }, [rangeStart, rangeEnd]);

  // Mirror video.currentTime → elapsed so the transcript-highlight + control
  // bar reflect the actual playhead. Throttled to ~4Hz by the browser via
  // the native timeupdate event. NEVER pause based on rangeEnd — that was
  // the bug that caused the Interview segment to "hang" at fbStart (~21s):
  // the video paused even though playback should continue into the feedback
  // portion naturally.
  const handleTimeUpdate = () => {
    const el = videoRef.current;
    if (!el) return;
    const t = Math.floor(el.currentTime);
    if (t !== elapsed) onElapsedChange(t);
  };

  return (
    <div id={id} className="flex flex-col">
      <div
        id={`${id}-stage`}
        ref={stageRef}
        className="relative aspect-[16/9] w-full overflow-hidden bg-[radial-gradient(circle_at_30%_25%,#2a2d33,#0f1012_70%)]"
      >
        {hasUrl ? (
          <video
            ref={videoRef}
            src={recordingUrl}
            controls
            preload="metadata"
            playsInline
            onPlay={() => onPlayingChange(true)}
            onPause={() => onPlayingChange(false)}
            onTimeUpdate={handleTimeUpdate}
            onLoadedMetadata={() => {
              const el = videoRef.current;
              if (el) el.currentTime = rangeStart;
            }}
            className="h-full w-full bg-black"
          >
            <track kind="captions" />
          </video>
        ) : (
          <>
            <div
              aria-hidden
              className="absolute inset-0 bg-[linear-gradient(110deg,rgba(255,255,255,0.05)_0%,rgba(255,255,255,0)_60%)]"
            />
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-center">
              <Video strokeWidth={1.5} aria-hidden className="h-8 w-8 text-white/40" />
              <p className="px-6 font-mono text-[11px] text-white/60 uppercase tracking-[0.14em]">
                Recording URL not yet available
              </p>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function FeedbackRequestModal({
  id,
  reqId,
  candidateId,
  roundId,
  defaultEmail,
  onClose,
}: {
  id: string;
  reqId: string;
  candidateId: string;
  roundId: string;
  defaultEmail: string;
  onClose: () => void;
}) {
  const [email, setEmail] = useState(defaultEmail);
  const [name, setName] = useState('');
  // Email is the only channel available right now (Slack intentionally disabled).
  const [channel] = useState<'email' | 'slack' | 'both'>('email');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await feedback.requestFeedback(reqId, candidateId, roundId, {
        interviewer_email: email,
        interviewer_name: name,
        channel,
      });
      onClose();
    } catch (err) {
      setError(err instanceof ServiceError ? err.message : 'Could not send request');
      setBusy(false);
    }
  };

  return (
    <ModalShell id={id} title="Request feedback" onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1">
          <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
            Interviewer
          </span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Jordan"
            className="rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary focus:border-text-primary focus:outline-none"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
            Email
          </span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary focus:border-text-primary focus:outline-none"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
            Channel
          </span>
          <select
            id="request-feedback-channel"
            value={channel}
            disabled
            aria-label="Feedback request channel"
            className="cursor-not-allowed rounded-[10px] border border-border bg-tile px-3 py-2 text-[13px] text-text-secondary focus:border-text-primary focus:outline-none"
          >
            <option value="email">Email</option>
          </select>
        </label>
        {error && <p className="text-[#B91C1C] text-[12.5px]">{error}</p>}
        <div className="mt-2 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-full border border-border bg-white px-3.5 py-2 text-[13px] text-text-muted hover:border-text-primary hover:text-text-primary"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            className={cn(
              'rounded-full px-3.5 py-2 font-medium text-[13px] transition-colors',
              busy
                ? 'cursor-not-allowed border border-border bg-surface text-text-faint'
                : 'border border-text-primary bg-text-primary text-white hover:bg-[#222]',
            )}
          >
            {busy ? 'Sending…' : 'Send request'}
          </button>
        </div>
      </form>
    </ModalShell>
  );
}

export function ModalShell({
  id,
  title,
  onClose,
  wide,
  children,
}: {
  id: string;
  title: string;
  onClose: () => void;
  wide?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      id={id}
      className="fixed inset-0 z-60 flex items-center justify-center bg-black/40 p-4"
      role="presentation"
    >
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-transparent"
      />
      <div
        role="dialog"
        aria-modal="true"
        className={cn(
          'relative w-full rounded-[16px] border border-border bg-white p-6 shadow-[0_20px_60px_rgba(0,0,0,0.2)]',
          wide ? 'max-w-2xl' : 'max-w-md',
        )}
      >
        <div className="mb-4 flex items-start justify-between gap-2">
          <h2 className="font-display text-[22px] text-text-primary leading-tight">{title}</h2>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-full text-text-muted hover:text-text-primary"
          >
            <X strokeWidth={1.75} className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function PrintPortal({ children }: { children: React.ReactNode }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  if (!mounted) return null;
  return createPortal(
    <div className="print-portal" style={{ display: 'none' }}>
      {children}
    </div>,
    document.body,
  );
}

function PrintableRoundPacket({
  candidateName,
  roleTitle,
  round,
  candidateRound,
  entries,
  questionSummaries,
}: {
  candidateName: string;
  roleTitle: string;
  round: Round;
  candidateRound: CandidateRound;
  entries: FeedbackEntry[];
  questionSummaries: Record<string, string>;
}) {
  const dateLabel = candidateRound.scheduled_at
    ? formatScheduledDate(
        candidateRound.scheduled_at,
        candidateRound.scheduling_timezone,
        'EEE, MMM d',
      )
    : '—';
  const timeLabel = candidateRound.scheduled_at
    ? formatScheduledTime(candidateRound.scheduled_at, candidateRound.scheduling_timezone)
    : '';
  const duration = round.duration_minutes;

  const pointsByQuestion = new Map<string, FeedbackEntry[]>();
  entries.forEach((e) => {
    const arr = pointsByQuestion.get(e.feedback_question_id) ?? [];
    arr.push(e);
    pointsByQuestion.set(e.feedback_question_id, arr);
  });

  const verdictColor = candidateRound.rating
    ? printVerdictColors(ratingToVerdictBucket(candidateRound.rating))
    : null;

  return (
    <div
      style={{
        fontFamily:
          'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        color: '#111',
        background: 'white',
        padding: '0',
      }}
    >
      <header style={{ marginBottom: '20px' }}>
        <p
          style={{
            fontFamily: 'ui-monospace, monospace',
            fontSize: '10px',
            textTransform: 'uppercase',
            letterSpacing: '0.14em',
            color: '#777',
            margin: 0,
          }}
        >
          Feedback packet
        </p>
        <h1 style={{ fontSize: '26px', margin: '4px 0 2px', fontWeight: 600 }}>{candidateName}</h1>
        <p style={{ fontSize: '13px', color: '#555', margin: 0 }}>
          {roleTitle} · Round {round.round_number}: {round.name}
        </p>
      </header>

      <section
        style={{
          border: '1px solid #e5e5e5',
          borderRadius: '12px',
          padding: '14px 16px',
          marginBottom: '14px',
          breakInside: 'avoid',
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            gap: '12px',
            marginBottom: '12px',
          }}
        >
          <div>
            <p
              style={{
                fontFamily: 'ui-monospace, monospace',
                fontSize: '10px',
                textTransform: 'uppercase',
                letterSpacing: '0.16em',
                color: '#777',
                margin: 0,
              }}
            >
              Round {round.round_number} · Interview
            </p>
            <h2 style={{ fontSize: '18px', margin: '4px 0 0', fontWeight: 600 }}>{round.name}</h2>
          </div>
          {candidateRound.feedback_approved_at && (
            <span
              style={{
                fontFamily: 'ui-monospace, monospace',
                fontSize: '10px',
                textTransform: 'uppercase',
                letterSpacing: '0.14em',
                padding: '3px 10px',
                border: '1px solid #A7F3D0',
                background: '#ECFDF5',
                color: '#047857',
                borderRadius: '999px',
              }}
            >
              Approved by interviewer
            </span>
          )}
        </div>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(2, 1fr)',
            gap: '10px',
            fontSize: '12px',
          }}
        >
          <PrintMeta label="When" value={`${dateLabel} ${timeLabel}`.trim()} />
          <PrintMeta label="Duration" value={duration ? `${duration} min` : '—'} />
          <PrintMeta label="Interviewer" value={candidateRound.interviewer_name ?? 'Unassigned'} />
          <PrintMeta label="Status" value={candidateRound.status} />
        </div>
      </section>

      {candidateRound.summary && (
        <section
          style={{
            border: '1px solid #e5e5e5',
            borderRadius: '12px',
            padding: '14px 16px',
            marginBottom: '14px',
            breakInside: 'avoid',
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'flex-start',
              gap: '12px',
              marginBottom: '8px',
            }}
          >
            <h3 style={{ fontSize: '15px', margin: 0, fontWeight: 600 }}>Round summary</h3>
            {candidateRound.rating && verdictColor && (
              <div style={{ textAlign: 'right' }}>
                <p
                  style={{
                    fontFamily: 'ui-monospace, monospace',
                    fontSize: '9px',
                    textTransform: 'uppercase',
                    letterSpacing: '0.18em',
                    color: '#999',
                    margin: 0,
                  }}
                >
                  Round verdict
                </p>
                <span
                  style={{
                    display: 'inline-block',
                    marginTop: '2px',
                    padding: '3px 10px',
                    border: `1px solid ${verdictColor.border}`,
                    background: verdictColor.bg,
                    color: verdictColor.fg,
                    fontSize: '12px',
                    fontWeight: 600,
                    textTransform: 'uppercase',
                    letterSpacing: '0.06em',
                    borderRadius: '6px',
                  }}
                >
                  {RATING_LABEL[candidateRound.rating]}
                </span>
              </div>
            )}
          </div>
          <p style={{ fontSize: '13px', lineHeight: 1.6, margin: 0, whiteSpace: 'pre-wrap' }}>
            {candidateRound.summary}
          </p>
        </section>
      )}

      <section>
        <h3 style={{ fontSize: '15px', margin: '0 0 10px', fontWeight: 600 }}>
          Evaluation criteria
        </h3>
        <ol style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {(round.feedback_questions ?? []).map((q, i) => {
            const points = pointsByQuestion.get(q.id) ?? [];
            const counts = points.reduce(
              (acc, p) => {
                acc[p.evidence_status] = (acc[p.evidence_status] ?? 0) + 1;
                return acc;
              },
              {} as Record<EvidenceStatus, number>,
            );
            // See EvaluationCriteria above: question_summaries is keyed by
            // question_number-as-string ('1', '2', ...) per the feedback Lambda
            // contract. The 1-indexed position matches the rendered label.
            const positionKey = String(i + 1);
            const summary = questionSummaries[positionKey] ?? questionSummaries[q.id];
            const visible = (
              ['supported', 'verified', 'partial', 'contradicted', 'none'] as EvidenceStatus[]
            ).filter((s) => (counts[s] ?? 0) > 0);
            return (
              <li
                key={q.id}
                style={{
                  border: '1px solid #e5e5e5',
                  borderRadius: '12px',
                  padding: '12px 14px',
                  marginBottom: '10px',
                  breakInside: 'avoid',
                }}
              >
                <p style={{ fontSize: '14px', fontWeight: 600, margin: 0 }}>
                  {i + 1}. {q.heading}
                </p>
                {q.description && (
                  <p style={{ fontSize: '12px', color: '#666', margin: '4px 0 0' }}>
                    {q.description}
                  </p>
                )}
                {summary && (
                  <div
                    style={{
                      marginTop: '8px',
                      padding: '8px 12px',
                      background: '#fafafa',
                      border: '1px solid #eee',
                      borderRadius: '8px',
                    }}
                  >
                    <p style={{ fontSize: '12.5px', lineHeight: 1.55, margin: 0 }}>{summary}</p>
                  </div>
                )}
                {visible.length > 0 && (
                  <div
                    style={{
                      display: 'flex',
                      flexWrap: 'wrap',
                      gap: '6px',
                      marginTop: '8px',
                    }}
                  >
                    {visible.map((s) => {
                      const n = counts[s] ?? 0;
                      const c = printChipColors(s);
                      return (
                        <span
                          key={s}
                          style={{
                            padding: '3px 10px',
                            border: `1px solid ${c.border}`,
                            background: c.bg,
                            color: c.fg,
                            fontSize: '11px',
                            borderRadius: '999px',
                            fontWeight: 500,
                          }}
                        >
                          {n} {ROLLUP_CHIP_LABEL[s]}
                        </span>
                      );
                    })}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      </section>
    </div>
  );
}

function PrintMeta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p
        style={{
          fontFamily: 'ui-monospace, monospace',
          fontSize: '9px',
          textTransform: 'uppercase',
          letterSpacing: '0.14em',
          color: '#999',
          margin: 0,
        }}
      >
        {label}
      </p>
      <p style={{ fontSize: '12.5px', margin: '2px 0 0', color: '#222' }}>{value}</p>
    </div>
  );
}

function printChipColors(s: EvidenceStatus): { bg: string; border: string; fg: string } {
  switch (s) {
    case 'supported':
    case 'verified':
      return { bg: '#ECFDF5', border: '#A7F3D0', fg: '#047857' };
    case 'partial':
      return { bg: '#FFFBEB', border: '#FDE68A', fg: '#B45309' };
    case 'contradicted':
      return { bg: '#FEF2F2', border: '#FECACA', fg: '#B91C1C' };
    case 'none':
      return { bg: '#FFFBEB', border: '#FDE68A', fg: '#B45309' };
  }
}

function printVerdictColors(s: EvidenceStatus): { bg: string; border: string; fg: string } {
  return printChipColors(s);
}
