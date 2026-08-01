'use client';

import {
  ChevronDown,
  ChevronUp,
  Clock,
  Download,
  Lightbulb,
  Pencil,
  Plus,
  Radar,
  Save,
  Share2,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { BrandIcon } from '@/components/icons/brand-icons';
import { ScreeningConfigPanel } from '@/components/screening/screening-config-panel';
import { useConfirm } from '@/components/ui/confirm-dialog';
import { useToast } from '@/components/ui/toast';
import type { FeedbackQuestion, Guideline, Requisition, Round, RoundType } from '@/domain';
import { useAutoSaveField } from '@/hooks/use-autosave-field';
import { getSharedRounds } from '@/lib/rounds';
import { cn } from '@/lib/utils';
import { requisitions } from '@/services';
import {
  getScreening,
  getScreeningSuggestion,
  type ScreeningConfig,
  type ScreeningSuggestion,
} from '@/services/screening';
import { ServiceError } from '@/services/service-error';
import { toPanelRound } from './screening-round-adapter';

interface PlanTabProps {
  id: string;
  role: Requisition;
}

function errMessage(err: unknown): string {
  if (err instanceof ServiceError) return err.message;
  if (err instanceof Error) return err.message;
  return 'Something went wrong';
}

function logErr(err: unknown): void {
  if (err instanceof ServiceError) {
    console.warn(`[plan-tab] ${err.code}: ${err.message}`);
  }
}

const ROUND_TYPE_LABELS: Record<RoundType, string> = {
  screening: 'Screening',
  technical: 'Technical',
  behavioral: 'Behavioral',
  culture: 'Culture',
  panel: 'Panel',
  final: 'Final',
};

const ROUND_TYPE_STYLE: Record<RoundType, string> = {
  screening: 'border-[#BFDBFE] bg-[#EFF6FF] text-[#1D4ED8]',
  technical: 'border-[#DDD6FE] bg-[#F5F3FF] text-[#6D28D9]',
  behavioral: 'border-[#FDE68A] bg-[#FFFBEB] text-[#B45309]',
  culture: 'border-[#A7F3D0] bg-[#ECFDF5] text-[#047857]',
  panel: 'border-[#FBCFE8] bg-[#FDF2F8] text-[#9D174D]',
  final: 'border-border bg-surface text-text-secondary',
};

const ROUND_TYPE_KEYS: readonly RoundType[] = [
  'screening',
  'technical',
  'behavioral',
  'culture',
  'panel',
  'final',
];

// rounds.category is free-text VARCHAR(50) in the backend, so it may arrive as
// "Screening", "PHONE_SCREEN", or anything else. Normalize to a canonical key
// when possible; otherwise return null so the UI can fall back to raw text.
function normalizeRoundType(raw: string | null | undefined): RoundType | null {
  if (!raw) return null;
  const key = raw.trim().toLowerCase();
  return (ROUND_TYPE_KEYS as readonly string[]).includes(key) ? (key as RoundType) : null;
}

export function PlanTab({ id, role }: PlanTabProps) {
  const [editing, setEditing] = useState(false);
  const [addingAt, setAddingAt] = useState<number | null>(null);
  // Which round's screening config panel is open (late-add entry point). The
  // Task-14 ScreeningConfigPanel owns generate/save/attach/invite via the real
  // screening API; we just mount it for the chosen round.
  const [screeningRound, setScreeningRound] = useState<Round | null>(null);

  const sharedRounds = getSharedRounds(role.rounds);
  const totalMinutes = sharedRounds.reduce((s, r) => s + r.duration_minutes, 0);

  // Light fetch of saved screening configs so each round row can reflect the
  // REAL enabled state (and question count) in its badge — instead of the old
  // mock `round.screening_agent_enabled`. Keyed by round id; missing = no config.
  const [screeningByRound, setScreeningByRound] = useState<Record<string, ScreeningConfig | null>>(
    {},
  );
  // Bumping this re-runs the fetch effect (e.g. after the panel closes) without
  // changing the round-id set it keys on.
  const [screeningNonce, setScreeningNonce] = useState(0);
  const refreshScreening = useCallback(() => setScreeningNonce((n) => n + 1), []);

  // Proactive "OpenRecruiting sees recurring gaps — add a screen?" nudge, driven by
  // Cortex. Fail-safe: a failed fetch (or no pattern) simply shows no banner —
  // it must never error the dashboard. Dismiss persists for the session.
  const [suggestion, setSuggestion] = useState<ScreeningSuggestion | null>(null);
  const dismissKey = `screening-suggestion-dismissed:${role.id}`;
  const [suggestionDismissed, setSuggestionDismissed] = useState(false);
  useEffect(() => {
    try {
      setSuggestionDismissed(sessionStorage.getItem(dismissKey) === '1');
    } catch {
      setSuggestionDismissed(false);
    }
  }, [dismissKey]);
  const dismissSuggestion = useCallback(() => {
    setSuggestionDismissed(true);
    try {
      sessionStorage.setItem(dismissKey, '1');
    } catch {}
  }, [dismissKey]);

  useEffect(() => {
    let cancelled = false;
    getScreeningSuggestion(role.id)
      .then((s) => {
        if (!cancelled) setSuggestion(s);
      })
      .catch(() => {
        // Silent: a failed suggestion fetch shows no banner, never an error.
        if (!cancelled) setSuggestion(null);
      });
    return () => {
      cancelled = true;
    };
  }, [role.id]);

  const roundIdsKey = sharedRounds.map((r) => r.id).join(',');
  // biome-ignore lint/correctness/useExhaustiveDependencies: roundIdsKey is the stable id-set key; depending on the round array identity would refetch every render.
  useEffect(() => {
    const roundIds = roundIdsKey ? roundIdsKey.split(',') : [];
    let cancelled = false;
    Promise.all(
      roundIds.map((roundId) =>
        getScreening(role.id, roundId)
          .then((cfg) => [roundId, cfg] as const)
          .catch(() => [roundId, null] as const),
      ),
    ).then((entries) => {
      if (cancelled) return;
      setScreeningByRound(Object.fromEntries(entries));
    });
    return () => {
      cancelled = true;
    };
  }, [role.id, roundIdsKey, screeningNonce]);

  return (
    <div id={id} className="flex flex-col gap-4">
      <header
        id={`${id}-head`}
        className="flex flex-wrap items-center justify-between gap-3 rounded-[14px] border border-border bg-white px-5 py-4"
      >
        <div id={`${id}-summary`} className="flex flex-wrap items-center gap-4">
          <div>
            <div className="font-display text-[22px] text-text-primary leading-none tracking-[-0.01em]">
              {sharedRounds.length}
            </div>
            <div className="mt-1 font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
              Rounds
            </div>
          </div>
          <span aria-hidden className="h-6 w-px bg-border" />
          <div>
            <div className="font-display text-[22px] text-text-primary leading-none tracking-[-0.01em]">
              {totalMinutes}
              <span className="ml-1 font-sans text-[12px] text-text-muted">min</span>
            </div>
            <div className="mt-1 font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
              Total time
            </div>
          </div>
        </div>
        <button
          id={`${id}-edit-toggle`}
          type="button"
          onClick={() => {
            setEditing((v) => !v);
            setAddingAt(null);
          }}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 font-medium font-sans text-[12.5px] transition-colors',
            editing
              ? 'border-text-primary bg-text-primary text-white hover:bg-[#222]'
              : 'border-border bg-white text-text-primary hover:border-text-primary',
          )}
        >
          {editing ? (
            <>
              <Save strokeWidth={1.75} className="h-3.5 w-3.5" />
              Done
            </>
          ) : (
            <>
              <Pencil strokeWidth={1.75} className="h-3.5 w-3.5" />
              Edit plan
            </>
          )}
        </button>
      </header>

      {editing && (
        <p id={`${id}-edit-help`} className="-mt-1 text-[12.5px] text-text-muted">
          Tap any round to reorder, rename, or adjust questions. Changes save automatically.
        </p>
      )}

      {suggestion?.shouldSuggest && !suggestionDismissed && (
        <ScreeningSuggestionBanner
          id={`${id}-suggestion`}
          reason={suggestion.reason}
          onAddScreening={() => {
            const target =
              sharedRounds.find((r) => r.id === suggestion.targetRoundId) ?? sharedRounds[0];
            if (target) setScreeningRound(target);
          }}
          onDismiss={dismissSuggestion}
        />
      )}

      {role.sourcing_strategies && role.sourcing_strategies.length > 0 && (
        <SavedStrategiesSection id={`${id}-strategies`} strategies={role.sourcing_strategies} />
      )}

      {editing && (
        <RoundInserter
          id={`${id}-ins-top`}
          roleId={role.id}
          position={0}
          open={addingAt === 0}
          onToggle={() => setAddingAt((v) => (v === 0 ? null : 0))}
          onDone={() => setAddingAt(null)}
        />
      )}

      {sharedRounds.map((round, i) => (
        <div key={round.id} className="flex flex-col gap-3">
          <RoundCard
            id={`${id}-round-${round.id}`}
            round={round}
            index={i}
            total={sharedRounds.length}
            editing={editing}
            screening={screeningByRound[round.id] ?? null}
            onConfigureScreening={() => setScreeningRound(round)}
          />
          {editing && (
            <RoundInserter
              id={`${id}-ins-${i + 1}`}
              roleId={role.id}
              position={i + 1}
              open={addingAt === i + 1}
              onToggle={() => setAddingAt((v) => (v === i + 1 ? null : i + 1))}
              onDone={() => setAddingAt(null)}
            />
          )}
        </div>
      ))}

      {screeningRound && (
        <ScreeningConfigPanel
          id={`${id}-screening-panel`}
          requisitionId={role.id}
          roundId={screeningRound.id}
          round={toPanelRound(screeningRound)}
          onClose={() => {
            setScreeningRound(null);
            // Re-read configs so the row badge reflects any attach/detach/edit
            // done inside the panel.
            refreshScreening();
          }}
        />
      )}
    </div>
  );
}

// Proactive late-add screen nudge. Cortex spotted a recurring gap across this
// role's completed rounds that an earlier screening round could catch. Dismissible
// (session-scoped); "Add screening" opens the Task-15 ScreeningConfigPanel for
// the suggested round.
function ScreeningSuggestionBanner({
  id,
  reason,
  onAddScreening,
  onDismiss,
}: {
  id: string;
  reason: string;
  onAddScreening: () => void;
  onDismiss: () => void;
}) {
  return (
    <div
      id={id}
      className="flex flex-wrap items-start gap-3 rounded-[14px] border border-cortex-500/30 bg-cortex-500/5 px-5 py-4"
    >
      <div
        aria-hidden
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-cortex-500/10 text-cortex-500"
      >
        <Lightbulb strokeWidth={1.75} className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <p
          id={`${id}-title`}
          className="font-display text-[15px] text-text-primary tracking-[-0.005em]"
        >
          OpenRecruiting sees recurring gaps in this role — add a screening round?
        </p>
        <p id={`${id}-reason`} className="mt-1 text-[12.5px] text-text-muted leading-[1.5]">
          {reason}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <button
          id={`${id}-add`}
          type="button"
          onClick={onAddScreening}
          className="inline-flex items-center gap-1.5 rounded-full border border-cortex-500/40 bg-white px-3.5 py-1.5 font-medium font-sans text-[12.5px] text-cortex-500 transition hover:bg-cortex-500/10"
        >
          <Sparkles strokeWidth={1.75} className="h-3.5 w-3.5" />
          Add screening
        </button>
        <button
          id={`${id}-dismiss`}
          type="button"
          aria-label="Dismiss suggestion"
          onClick={onDismiss}
          className="flex h-7 w-7 items-center justify-center rounded-full text-text-muted hover:bg-white hover:text-text-primary"
        >
          <X strokeWidth={1.75} className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

// The round's editable core, persisted as one unit so changing type then
// category never races (both go in the same explicit commit). `category` is
// the raw free-text string actually persisted; `type` is the normalized key
// for label/style lookup, derived from `category`.
interface RoundCore {
  name: string;
  duration_minutes: number;
  category: string;
}

function RoundCard({
  id,
  round,
  index,
  total,
  editing,
  screening,
  onConfigureScreening,
}: {
  id: string;
  round: Round;
  index: number;
  total: number;
  editing: boolean;
  screening: ScreeningConfig | null;
  onConfigureScreening: () => void;
}) {
  const { showToast } = useToast();
  const confirm = useConfirm();
  const [expanded, setExpanded] = useState(index === 0);

  // Real screening state from the saved config (not the legacy mock flag).
  const aiHosted = screening?.enabled === true;
  const screeningQuestionCount = screening?.questions.length ?? 0;
  // Eligibility nudge: backend says OpenRecruiting can host this round but it isn't
  // attached yet. Suppressed once hosted (the "takes this round" badge wins).
  const aiEligible = round.aiScreenable === true && !aiHosted;

  const core = useAutoSaveField<RoundCore>(
    {
      name: round.name,
      duration_minutes: round.duration_minutes,
      category: round.category ?? '',
    },
    (next) =>
      requisitions.updateRound(round.id, {
        name: next.name,
        duration_minutes: next.duration_minutes,
        category: next.category,
      }),
    {
      onError: (err) => showToast(`Could not save round: ${errMessage(err)}`, 'error'),
      isEqual: (a, b) =>
        a.name === b.name && a.duration_minutes === b.duration_minutes && a.category === b.category,
    },
  );

  const name = core.value.name;
  const duration = core.value.duration_minutes;
  const rawCategory = core.value.category;
  const type = normalizeRoundType(rawCategory);

  return (
    <article
      id={id}
      className="rounded-[16px] border border-border bg-white p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition-shadow hover:shadow-[0_2px_8px_rgba(0,0,0,0.04)]"
    >
      <header
        className="flex items-start justify-between gap-3 cursor-pointer select-none"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <span
            aria-hidden
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface font-medium font-mono text-[12px] text-text-primary"
          >
            {round.round_number}
          </span>
          <div className="min-w-0 flex-1">
            {editing ? (
              <input
                id={`${id}-name`}
                value={name}
                onClick={(e) => e.stopPropagation()}
                onChange={(e) => core.setValue({ ...core.value, name: e.target.value })}
                onBlur={() => core.commit()}
                aria-invalid={core.status === 'error'}
                className={cn(
                  'w-full border-0 bg-transparent font-display text-[20px] text-text-primary tracking-[-0.005em] placeholder:text-text-muted focus:outline-none',
                  core.status === 'error' && 'text-[#B91C1C]',
                )}
                placeholder="Round name"
              />
            ) : (
              <h3 className="font-display text-[20px] text-text-primary leading-tight tracking-[-0.005em]">
                {name}
              </h3>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {editing ? (
                <select
                  id={`${id}-type`}
                  value={type ?? ''}
                  onClick={(e) => e.stopPropagation()}
                  onChange={(e) => {
                    const next = e.target.value as RoundType | '';
                    if (next === '') return;
                    // Persist the CURRENT values atomically with the new
                    // category — explicit value, no setTimeout/stale closure.
                    core.commit({ ...core.value, category: next });
                  }}
                  className={cn(
                    'rounded-full border px-2.5 py-0.5 font-medium font-mono text-[10.5px] uppercase tracking-[0.14em] focus:outline-none',
                    type ? ROUND_TYPE_STYLE[type] : 'border-border bg-surface text-text-secondary',
                  )}
                >
                  {type === null && (
                    <option value="" disabled>
                      {rawCategory || 'Select a type'}
                    </option>
                  )}
                  {ROUND_TYPE_KEYS.map((t) => (
                    <option key={t} value={t}>
                      {ROUND_TYPE_LABELS[t]}
                    </option>
                  ))}
                </select>
              ) : type ? (
                <span
                  className={cn(
                    'inline-flex items-center rounded-full border px-2.5 py-0.5 font-medium font-mono text-[10.5px] uppercase tracking-[0.14em]',
                    ROUND_TYPE_STYLE[type],
                  )}
                >
                  {ROUND_TYPE_LABELS[type]}
                </span>
              ) : rawCategory ? (
                <span className="inline-flex items-center rounded-full border border-border bg-surface px-2.5 py-0.5 font-medium font-mono text-[10.5px] text-text-secondary uppercase tracking-[0.14em]">
                  {rawCategory}
                </span>
              ) : null}
              <span className="inline-flex items-center gap-1 rounded-full border border-border bg-surface px-2.5 py-0.5 font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
                <Clock strokeWidth={1.75} className="h-3 w-3" />
                {editing ? (
                  <input
                    id={`${id}-duration`}
                    type="number"
                    min={15}
                    max={240}
                    step={15}
                    value={duration}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) =>
                      core.setValue({
                        ...core.value,
                        duration_minutes: Number.parseInt(e.target.value, 10) || 0,
                      })
                    }
                    onBlur={() => core.commit()}
                    className="w-10 border-0 bg-transparent p-0 text-[10.5px] text-text-primary focus:outline-none"
                  />
                ) : (
                  <span className="text-text-primary">{duration}</span>
                )}
                min
              </span>
              <span className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]">
                {round.feedback_questions.length} question
                {round.feedback_questions.length === 1 ? '' : 's'}
              </span>
              {aiHosted && (
                <button
                  id={`${id}-screening-badge`}
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onConfigureScreening();
                  }}
                  className="inline-flex items-center gap-1 rounded-full border border-cortex-500/30 bg-white px-2 py-0.5 font-medium font-mono text-[10px] text-cortex-500 uppercase tracking-[0.14em] transition hover:bg-cortex-500/10"
                >
                  <BrandIcon className="h-2.5 w-2.5" />
                  OpenRecruiting takes this round
                  {screeningQuestionCount > 0 ? ` · ${screeningQuestionCount}Q` : ''}
                </button>
              )}
              {aiEligible && (
                <button
                  id={`${id}-screening-nudge`}
                  type="button"
                  title={
                    round.aiScreenableReason ?? 'OpenRecruiting can host this round as a screening call.'
                  }
                  onClick={(e) => {
                    e.stopPropagation();
                    onConfigureScreening();
                  }}
                  className="inline-flex items-center gap-1 rounded-full border border-cortex-500/30 border-dashed bg-cortex-500/5 px-2 py-0.5 font-medium font-mono text-[10px] text-cortex-500 uppercase tracking-[0.14em] transition hover:bg-cortex-500/10"
                >
                  <BrandIcon className="h-2.5 w-2.5" />
                  OpenRecruiting can take this round
                </button>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            aria-label="Toggle details"
            onClick={() => setExpanded((v) => !v)}
            className="flex h-7 w-7 items-center justify-center rounded-full text-text-muted hover:bg-surface hover:text-text-primary"
          >
            {expanded ? (
              <ChevronUp strokeWidth={1.75} className="h-4 w-4" />
            ) : (
              <ChevronDown strokeWidth={1.75} className="h-4 w-4" />
            )}
          </button>
          {editing && (
            <button
              type="button"
              aria-label="Delete round"
              disabled={total <= 1}
              onClick={async () => {
                const ok = await confirm({
                  title: `Delete "${round.name}"?`,
                  body: 'This removes the round and its feedback questions from the plan.',
                  confirmLabel: 'Delete round',
                  danger: true,
                });
                if (!ok) return;
                try {
                  await requisitions.deleteRound(round.id);
                } catch (err) {
                  logErr(err);
                  showToast(`Could not delete round: ${errMessage(err)}`, 'error');
                }
              }}
              className={cn(
                'flex h-7 w-7 items-center justify-center rounded-full transition-colors',
                total <= 1
                  ? 'text-text-faint'
                  : 'text-text-muted hover:bg-[#FEF2F2] hover:text-[#B91C1C]',
              )}
            >
              <Trash2 strokeWidth={1.75} className="h-4 w-4" />
            </button>
          )}
        </div>
      </header>

      {expanded && <DescriptionSection id={`${id}-description`} round={round} editing={editing} />}
      {expanded && <SkillsSection id={`${id}-skills`} round={round} editing={editing} />}
      {expanded && <QuestionsSection id={`${id}-questions`} round={round} editing={editing} />}
      {expanded && <GuidelinesSection id={`${id}-guidelines`} round={round} editing={editing} />}
      {expanded && (
        <ScreeningAgentSection
          id={`${id}-screening`}
          screening={screening}
          eligible={aiEligible}
          onConfigure={onConfigureScreening}
        />
      )}
    </article>
  );
}

function DescriptionSection({
  id,
  round,
  editing,
}: {
  id: string;
  round: Round;
  editing: boolean;
}) {
  const { showToast } = useToast();
  const field = useAutoSaveField<string>(
    round.description ?? '',
    (next) => requisitions.updateRound(round.id, { description: next }),
    { onError: (err) => showToast(`Could not save description: ${errMessage(err)}`, 'error') },
  );
  if (!editing && !round.description) return null;
  return (
    <section id={id} className="mt-4 flex flex-col gap-2 border-border border-t pt-4">
      <p className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]">
        Description
      </p>
      {editing ? (
        <textarea
          id={`${id}-input`}
          value={field.value}
          onChange={(e) => field.setValue(e.target.value)}
          onBlur={() => field.commit()}
          aria-invalid={field.status === 'error'}
          rows={3}
          placeholder="What this round is for, what the interviewer should focus on…"
          className={cn(
            'resize-y rounded-[10px] border bg-white px-3 py-2 text-[13px] text-text-primary placeholder:text-text-muted focus:outline-none',
            field.status === 'error'
              ? 'border-[#FCA5A5] focus:border-[#B91C1C]'
              : 'border-border focus:border-text-primary',
          )}
        />
      ) : (
        <p className="text-[13px] text-text-secondary leading-[1.55]">{round.description}</p>
      )}
    </section>
  );
}

function SkillsSection({ id, round, editing }: { id: string; round: Round; editing: boolean }) {
  const { showToast } = useToast();
  const [newSkill, setNewSkill] = useState('');
  const skills = round.skills;
  const commit = (next: string[]) => {
    requisitions.updateRound(round.id, { skills: next }).catch((err) => {
      logErr(err);
      showToast(`Could not save skills: ${errMessage(err)}`, 'error');
    });
  };
  const add = () => {
    const v = newSkill.trim();
    if (!v) return;
    if (skills.includes(v)) {
      setNewSkill('');
      return;
    }
    commit([...skills, v]);
    setNewSkill('');
  };
  const remove = (i: number) => {
    commit(skills.filter((_, idx) => idx !== i));
  };
  if (!editing && skills.length === 0) return null;
  return (
    <section id={id} className="mt-4 flex flex-col gap-2 border-border border-t pt-4">
      <p className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]">Skills</p>
      <div className="flex flex-wrap items-center gap-1.5">
        {skills.length === 0 && !editing && (
          <span className="text-[12.5px] text-text-muted italic">No skills tagged.</span>
        )}
        {skills.map((s, i) => (
          <span
            key={`${s}_${i}`}
            id={`${id}-tag-${i}`}
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-0.5 font-mono text-[10.5px] text-text-secondary uppercase tracking-[0.12em]"
          >
            {s}
            {editing && (
              <button
                id={`${id}-tag-${i}-remove`}
                type="button"
                aria-label={`Remove ${s}`}
                onClick={() => remove(i)}
                className="-mr-1 flex h-4 w-4 items-center justify-center rounded-full text-text-muted hover:bg-white hover:text-[#B91C1C]"
              >
                <X strokeWidth={2} className="h-3 w-3" />
              </button>
            )}
          </span>
        ))}
      </div>
      {editing && (
        <div className="flex items-center gap-2">
          <input
            id={`${id}-new`}
            value={newSkill}
            onChange={(e) => setNewSkill(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                add();
              }
            }}
            placeholder="Add a skill and press Enter"
            className="flex-1 rounded-[8px] border border-border bg-white px-3 py-1.5 text-[12.5px] text-text-primary placeholder:text-text-muted focus:border-text-primary focus:outline-none"
          />
          <button
            id={`${id}-add`}
            type="button"
            onClick={add}
            disabled={!newSkill.trim()}
            className={cn(
              'inline-flex items-center gap-1 rounded-full px-3 py-1 font-medium text-[12px] transition-colors',
              newSkill.trim()
                ? 'border border-text-primary bg-text-primary text-white hover:bg-[#222]'
                : 'cursor-not-allowed border border-border bg-surface text-text-faint',
            )}
          >
            <Plus strokeWidth={1.75} className="h-3 w-3" />
            Add
          </button>
        </div>
      )}
    </section>
  );
}

function GuidelinesSection({ id, round, editing }: { id: string; round: Round; editing: boolean }) {
  const { showToast } = useToast();
  const guidelines = round.guidelines;
  const [drafts, setDrafts] = useState<Guideline[]>(guidelines);
  useEffect(() => {
    setDrafts(guidelines);
  }, [guidelines]);
  const commit = (next: Guideline[]) => {
    setDrafts(next);
    requisitions.updateRound(round.id, { guidelines: next }).catch((err) => {
      logErr(err);
      showToast(`Could not save guidelines: ${errMessage(err)}`, 'error');
    });
  };
  const setDraftField = (i: number, patch: Partial<Guideline>) => {
    setDrafts((curr) => curr.map((g, idx) => (idx === i ? { ...g, ...patch } : g)));
  };
  const flushIfChanged = (i: number) => {
    const draft = drafts[i];
    const original = guidelines[i];
    if (!draft || !original) return;
    if (draft.title !== original.title || draft.description !== original.description) {
      commit(drafts.map((g, idx) => (idx === i ? { ...draft } : g)));
    }
  };
  const remove = (i: number) => commit(drafts.filter((_, idx) => idx !== i));
  const add = () => commit([...drafts, { title: '', description: '' }]);
  if (!editing && drafts.length === 0) return null;
  return (
    <section id={id} className="mt-4 flex flex-col gap-2 border-border border-t pt-4">
      <p className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]">
        Interviewer guidelines
      </p>
      {drafts.length === 0 && !editing && (
        <p className="text-[12.5px] text-text-muted italic">No guidelines yet.</p>
      )}
      <ul className="flex flex-col gap-2">
        {drafts.map((g, i) => (
          <li
            key={i}
            id={`${id}-row-${i}`}
            className="flex items-start gap-3 rounded-[12px] border border-border bg-white p-3.5"
          >
            <span
              aria-hidden
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface font-mono text-[10px] text-text-muted"
            >
              {i + 1}
            </span>
            <div className="flex flex-1 flex-col gap-1">
              {editing ? (
                <>
                  <input
                    id={`${id}-row-${i}-title`}
                    value={g.title}
                    onChange={(e) => setDraftField(i, { title: e.target.value })}
                    onBlur={() => flushIfChanged(i)}
                    placeholder="Guideline title"
                    className="rounded-[8px] border border-border bg-white px-2.5 py-1.5 font-medium text-[13.5px] text-text-primary placeholder:text-text-muted focus:border-text-primary focus:outline-none"
                  />
                  <textarea
                    id={`${id}-row-${i}-description`}
                    value={g.description}
                    onChange={(e) => setDraftField(i, { description: e.target.value })}
                    onBlur={() => flushIfChanged(i)}
                    placeholder="What to do during this round (optional)"
                    rows={2}
                    className="resize-y rounded-[8px] border border-border bg-white px-2.5 py-1.5 text-[12.5px] text-text-secondary placeholder:text-text-muted focus:border-text-primary focus:outline-none"
                  />
                </>
              ) : (
                <>
                  <p className="font-medium text-[13.5px] text-text-primary">{g.title}</p>
                  {g.description && (
                    <p className="text-[12.5px] text-text-muted leading-[1.5]">{g.description}</p>
                  )}
                </>
              )}
            </div>
            {editing && (
              <button
                id={`${id}-row-${i}-remove`}
                type="button"
                aria-label="Delete guideline"
                onClick={() => remove(i)}
                className="flex h-7 w-7 items-center justify-center rounded-full text-text-muted hover:bg-[#FEF2F2] hover:text-[#B91C1C]"
              >
                <Trash2 strokeWidth={1.75} className="h-3.5 w-3.5" />
              </button>
            )}
          </li>
        ))}
      </ul>
      {editing && (
        <div className="flex justify-end">
          <button
            id={`${id}-add`}
            type="button"
            onClick={add}
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-white px-3 py-1 font-medium text-[12px] text-text-primary hover:border-text-primary"
          >
            <Plus strokeWidth={1.75} className="h-3.5 w-3.5" />
            Add guideline
          </button>
        </div>
      )}
    </section>
  );
}

function SavedStrategiesSection({
  id,
  strategies,
}: {
  id: string;
  strategies: NonNullable<Requisition['sourcing_strategies']>;
}) {
  return (
    <section id={id} className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
          Saved sourcing strategies · {strategies.length}
        </span>
      </div>
      <ul className="flex flex-col gap-2">
        {strategies.map((s) => (
          <li
            key={s.id}
            id={`${id}-row-${s.id}`}
            className="grid grid-cols-[auto_1fr_auto_auto] items-center gap-3 rounded-[14px] border border-border bg-white p-3.5"
          >
            <div
              aria-hidden
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-[#111] text-white"
            >
              <Radar strokeWidth={1.75} className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <div className="truncate font-medium text-[13.5px] text-text-primary">
                Sourcing strategy v{s.version}
              </div>
              <div className="truncate text-[11.5px] text-text-muted">
                {s.candidate_count} shortlisted · {s.total_profiles_label} · by {s.owner_name}
              </div>
            </div>
            <button
              type="button"
              aria-label="Share"
              className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-border bg-white text-text-muted hover:border-text-primary hover:text-text-primary"
              onClick={() => {
                try {
                  if (typeof navigator !== 'undefined' && navigator.clipboard) {
                    void navigator.clipboard.writeText(window.location.href);
                  }
                } catch {}
              }}
            >
              <Share2 strokeWidth={1.75} className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              aria-label="Download"
              className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-border bg-white text-text-muted hover:border-text-primary hover:text-text-primary"
              onClick={() => {
                const blob = new Blob([JSON.stringify(s, null, 2)], {
                  type: 'application/json',
                });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `sourcing-strategy-${s.id}.json`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
              }}
            >
              <Download strokeWidth={1.75} className="h-3.5 w-3.5" />
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

// Screening summary inside an expanded round. Driven by the REAL saved config
// (not the legacy mock). Offers the late-add entry point into the Task-14
// ScreeningConfigPanel, which owns generate/save/attach/invite.
//
// Recruiter-override: this entry is ALWAYS available on an expanded round so the
// recruiter can set up screening even when the intake flag is absent (the flag
// comes from the not-yet-deployed intake Lambda). Eligible/enabled rounds keep
// the prominent treatment; a round that is neither gets a lighter affordance
// (muted copy) — reachable but not auto-recommended.
function ScreeningAgentSection({
  id,
  screening,
  eligible,
  onConfigure,
}: {
  id: string;
  screening: ScreeningConfig | null;
  eligible: boolean;
  onConfigure: () => void;
}) {
  const enabled = screening?.enabled === true;
  const questions = screening?.questions ?? [];
  // Prominent for hosted/eligible rounds; lighter (muted, non-recommended) for
  // a round that is neither — the recruiter-override path.
  const prominent = enabled || eligible;
  return (
    <div
      id={id}
      className={cn(
        'mt-4 flex flex-col gap-2 rounded-[12px] p-3.5',
        prominent ? 'border border-cortex-500/30 bg-cortex-500/5' : 'border border-border bg-white',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span
          className={cn(
            'inline-flex items-center gap-1.5 font-mono text-[10.5px] uppercase tracking-[0.14em]',
            prominent ? 'text-cortex-500' : 'text-text-muted',
          )}
        >
          <BrandIcon className="h-3 w-3" />
          OpenRecruiting screening agent
        </span>
        <button
          id={`${id}-configure`}
          type="button"
          onClick={onConfigure}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-full border bg-white px-3 py-1 font-medium font-mono text-[10px] uppercase tracking-[0.14em] transition',
            prominent
              ? 'border-cortex-500/40 text-cortex-500 hover:bg-cortex-500/10'
              : 'border-border text-text-secondary hover:border-text-primary hover:text-text-primary',
          )}
        >
          <Sparkles strokeWidth={1.75} className="h-3 w-3" />
          {enabled ? 'Configure' : 'Set up screening'}
        </button>
      </div>
      {!enabled ? (
        <p className="text-[12.5px] text-text-muted">
          {eligible
            ? 'OpenRecruiting can host this round as a screening call. Set it up to generate questions and invite candidates.'
            : 'OpenRecruiting can run conversational rounds (screening, recruiter, behavioral) as a voice screen. Set it up to generate questions and invite candidates.'}
        </p>
      ) : questions.length === 0 ? (
        <p className="text-[12.5px] text-text-muted italic">
          Screening attached but no questions yet — open Configure to generate.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {questions.map((q, i) => (
            <li
              key={q.id ?? `q-${i}`}
              id={`${id}-q-${i}`}
              className="rounded-[10px] border border-cortex-500/20 bg-white p-3 text-[12.5px]"
            >
              <div className="mb-1 font-mono text-[10px] text-cortex-500 uppercase tracking-[0.14em]">
                Q0{i + 1} · {q.dimension}
              </div>
              <p className="font-medium text-[13px] text-text-primary">{q.title}</p>
              {q.probe && (
                <p className="mt-1 font-serif text-[12px] text-text-muted italic">
                  ↳ probe: {q.probe}
                </p>
              )}
              <div className="mt-2 flex gap-3 border-border border-t pt-1.5 font-mono text-[9.5px] text-text-muted uppercase tracking-[0.14em]">
                <span>{q.durationMinutes} min</span>
                <span>{q.signal}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function QuestionsSection({ id, round, editing }: { id: string; round: Round; editing: boolean }) {
  const { showToast } = useToast();
  const [heading, setHeading] = useState('');
  const [description, setDescription] = useState('');

  const add = async () => {
    if (!heading.trim()) return;
    try {
      await requisitions.addQuestion(round.id, { heading, description });
      setHeading('');
      setDescription('');
    } catch (err) {
      logErr(err);
      showToast(`Could not add question: ${errMessage(err)}`, 'error');
    }
  };

  return (
    <div id={id} className="mt-4 flex flex-col gap-2 border-border border-t pt-4">
      <p className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]">
        Feedback questions
      </p>
      {round.feedback_questions.length === 0 && !editing && (
        <p className="text-[12.5px] text-text-muted italic">
          No questions yet. Click “Edit plan” to add some.
        </p>
      )}
      <ul className="flex flex-col gap-2">
        {round.feedback_questions.map((q, i) => (
          <QuestionRow key={q.id} id={`${id}-q-${q.id}`} question={q} index={i} editing={editing} />
        ))}
      </ul>
      {editing && (
        <div className="mt-2 flex flex-col gap-2 rounded-[12px] border border-border border-dashed bg-surface/40 p-3">
          <input
            id={`${id}-new-heading`}
            value={heading}
            onChange={(e) => setHeading(e.target.value)}
            placeholder="New question heading (e.g. Product sense)"
            className="rounded-[8px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary placeholder:text-text-muted focus:border-text-primary focus:outline-none"
          />
          <input
            id={`${id}-new-desc`}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Optional prompt / what to listen for"
            className="rounded-[8px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary placeholder:text-text-muted focus:border-text-primary focus:outline-none"
          />
          <div className="flex justify-end">
            <button
              id={`${id}-new-add`}
              type="button"
              onClick={add}
              disabled={!heading.trim()}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 font-medium text-[12px] transition-colors',
                heading.trim()
                  ? 'border border-text-primary bg-text-primary text-white hover:bg-[#222]'
                  : 'cursor-not-allowed border border-border bg-surface text-text-faint',
              )}
            >
              <Plus strokeWidth={1.75} className="h-3.5 w-3.5" />
              Add question
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function QuestionRow({
  id,
  question,
  index,
  editing,
}: {
  id: string;
  question: FeedbackQuestion;
  index: number;
  editing: boolean;
}) {
  const { showToast } = useToast();
  const confirm = useConfirm();
  const field = useAutoSaveField<{ heading: string; description: string }>(
    { heading: question.heading, description: question.description },
    (next) =>
      requisitions.updateQuestion(question.id, {
        heading: next.heading,
        description: next.description,
      }),
    {
      onError: (err) => showToast(`Could not save question: ${errMessage(err)}`, 'error'),
      isEqual: (a, b) => a.heading === b.heading && a.description === b.description,
    },
  );
  const heading = field.value.heading;
  const description = field.value.description;

  return (
    <li
      id={id}
      className="flex items-start gap-3 rounded-[12px] border border-border bg-white p-3.5"
    >
      <span
        aria-hidden
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface font-mono text-[10px] text-text-muted"
      >
        {index + 1}
      </span>
      <div className="flex flex-1 flex-col gap-1">
        {editing ? (
          <>
            <input
              id={`${id}-heading`}
              value={heading}
              onChange={(e) => field.setValue({ ...field.value, heading: e.target.value })}
              onBlur={() => field.commit()}
              aria-invalid={field.status === 'error'}
              className={cn(
                'border-0 bg-transparent font-medium text-[13.5px] text-text-primary focus:outline-none',
                field.status === 'error' && 'text-[#B91C1C]',
              )}
            />
            <input
              id={`${id}-desc`}
              value={description}
              onChange={(e) => field.setValue({ ...field.value, description: e.target.value })}
              onBlur={() => field.commit()}
              placeholder="What to probe for (optional)"
              className="border-0 bg-transparent text-[12.5px] text-text-muted placeholder:text-text-faint focus:outline-none"
            />
          </>
        ) : (
          <>
            <p className="font-medium text-[13.5px] text-text-primary">{heading}</p>
            {description && (
              <p className="text-[12.5px] text-text-muted leading-[1.5]">{description}</p>
            )}
          </>
        )}
      </div>
      {editing && (
        <button
          type="button"
          aria-label="Delete question"
          onClick={async () => {
            const ok = await confirm({
              title: 'Delete this question?',
              body: heading ? `"${heading}" will be removed from the round.` : undefined,
              confirmLabel: 'Delete question',
              danger: true,
            });
            if (!ok) return;
            try {
              await requisitions.deleteQuestion(question.id);
            } catch (err) {
              logErr(err);
              showToast(`Could not delete question: ${errMessage(err)}`, 'error');
            }
          }}
          className="flex h-7 w-7 items-center justify-center rounded-full text-text-muted hover:bg-[#FEF2F2] hover:text-[#B91C1C]"
        >
          <Trash2 strokeWidth={1.75} className="h-3.5 w-3.5" />
        </button>
      )}
    </li>
  );
}

function RoundInserter({
  id,
  roleId,
  position,
  open,
  onToggle,
  onDone,
}: {
  id: string;
  roleId: string;
  position: number;
  open: boolean;
  onToggle: () => void;
  onDone: () => void;
}) {
  const { showToast } = useToast();
  const [name, setName] = useState('');
  const [type, setType] = useState<RoundType>('behavioral');
  const [duration, setDuration] = useState(45);

  if (!open) {
    return (
      <button
        id={id}
        type="button"
        onClick={onToggle}
        className="mx-auto inline-flex items-center gap-1 rounded-full border border-border border-dashed bg-white px-3 py-1 text-[11.5px] text-text-secondary transition-colors hover:border-text-primary hover:text-text-primary"
      >
        <Plus strokeWidth={1.75} className="h-3 w-3" />
        Insert round
      </button>
    );
  }

  return (
    <div
      id={id}
      className="flex flex-col gap-2 rounded-[12px] border border-border bg-surface/40 p-3"
    >
      <input
        id={`${id}-name`}
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Round name"
        className="rounded-[8px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary focus:border-text-primary focus:outline-none"
      />
      <div className="flex gap-2">
        <select
          id={`${id}-type`}
          value={type}
          onChange={(e) => setType(e.target.value as RoundType)}
          className="rounded-[8px] border border-border bg-white px-2 py-1.5 text-[12px] text-text-primary focus:border-text-primary focus:outline-none"
        >
          {(
            ['screening', 'technical', 'behavioral', 'culture', 'panel', 'final'] as RoundType[]
          ).map((t) => (
            <option key={t} value={t}>
              {ROUND_TYPE_LABELS[t]}
            </option>
          ))}
        </select>
        <input
          id={`${id}-duration`}
          type="number"
          min={15}
          max={240}
          step={15}
          value={duration}
          onChange={(e) => setDuration(Number.parseInt(e.target.value, 10) || 0)}
          className="w-20 rounded-[8px] border border-border bg-white px-2 py-1.5 text-[12px] text-text-primary focus:border-text-primary focus:outline-none"
        />
      </div>
      <div className="flex justify-end gap-2">
        <button
          id={`${id}-cancel`}
          type="button"
          onClick={onToggle}
          className="inline-flex items-center gap-1 rounded-full border border-border bg-white px-3 py-1 text-[12px] text-text-muted hover:border-text-primary hover:text-text-primary"
        >
          <X strokeWidth={1.75} className="h-3 w-3" />
          Cancel
        </button>
        <button
          id={`${id}-submit`}
          type="button"
          disabled={!name.trim()}
          onClick={async () => {
            try {
              await requisitions.addRound(roleId, {
                name,
                category: type,
                duration_minutes: duration,
                position,
              });
              onDone();
            } catch (err) {
              logErr(err);
              showToast(`Could not add round: ${errMessage(err)}`, 'error');
            }
          }}
          className={cn(
            'rounded-full px-3 py-1 font-medium text-[12px] transition-colors',
            name.trim()
              ? 'border border-text-primary bg-text-primary text-white hover:bg-[#222]'
              : 'cursor-not-allowed border border-border bg-surface text-text-faint',
          )}
        >
          Add round
        </button>
      </div>
    </div>
  );
}
