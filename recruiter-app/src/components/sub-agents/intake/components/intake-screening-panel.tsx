'use client';

// Draft (pre-publish) screening config panel for the intake plan editor.
//
// Unlike the post-publish `ScreeningConfigPanel` (which is DB-backed: get/save/
// attach/invite against a real round_id), this panel operates ENTIRELY on an
// in-memory `RoundScreening` object and reports every change through `onChange`.
// The editor persists it into the plan artifact, and publish materializes it —
// there are NO get/save/attach/invite calls here (no round exists yet, and no
// candidates exist pre-publish, so there is no invite section either).
//
// Generate questions → POST .../screening/generate (return-only draft).
// Derive persona     → POST .../screening/persona/derive (return-only draft).
//
// Persona draft-edit choice: the derived snapshot is stored verbatim. Editing a
// dimension (or a tone knob) updates `personaSnapshot.dimensions` AND recomposes
// `personaSnapshot.text` from the dimensions while PRESERVING the guardrails tail
// of the derived text — the backend trusts `text` at runtime, so it must stay
// consistent with the edited dimensions, but we must never drop the guardrails.

import { Check, Loader2, Sparkles, X } from 'lucide-react';
import { useCallback, useMemo, useRef, useState } from 'react';
import { PersonaToneKnobs } from '@/components/screening/persona-tone-knobs';
import { ScreeningQuestionCard } from '@/components/screening/screening-question-card';
import { useToast } from '@/components/ui/toast';
import { useFocusTrap } from '@/hooks/use-focus-trap';
import {
  derivePersonaDraft,
  generateScreeningDraft,
  type PersonaDimension,
  type PersonaSource,
  type ScreeningQuestion,
} from '@/services/screening';
import { ServiceError } from '@/services/service-error';
import type { InterviewPlanRound, RoundScreening } from '@/types/intake';

export interface IntakeScreeningPanelProps {
  id: string;
  sessionId: string;
  round: InterviewPlanRound;
  /** Current draft screening for the round (undefined when none yet). */
  screening: RoundScreening | undefined;
  /** Persist the next draft into the plan artifact (undefined clears it). */
  onChange: (next: RoundScreening | undefined) => void;
  onClose: () => void;
}

// Conventional presets (backend stores voice/follow-up as free text). Defaults
// match the post-publish panel so a recruiter sees the same options.
const DEFAULT_VOICE = 'Aura · "Luna"';
const DEFAULT_FOLLOW_UP = 'Adaptive probes';
const VOICE_OPTIONS = [DEFAULT_VOICE, 'Aura · "Orion"', 'Aura · "Stella"'];
const FOLLOW_UP_OPTIONS = [DEFAULT_FOLLOW_UP, 'Fixed script', 'Light touch'];
const DEFAULT_VALIDITY_DAYS = 7;

const DIMENSION_LABELS: Record<string, string> = {
  tone_rapport: 'Tone & rapport',
  probing_depth: 'Probing depth & follow-up style',
  eval_priorities: 'Evaluation priorities / signals',
  must_haves: 'Must-haves / dealbreakers',
  structure: 'Structure & time budget',
};
const DIMENSION_ORDER = Object.keys(DIMENSION_LABELS);

const SOURCE_LABELS: Record<PersonaSource, string> = {
  cortex: 'Cortex',
  generic: 'Generic',
  recruiter: 'Edited',
};

// The guardrails block the backend always appends. Recomposing client-side must
// preserve it (the runtime persona depends on it). We splice the body from the
// edited dimensions and keep this tail from the original derived text.
const GUARDRAILS_MARKER = 'NON-NEGOTIABLE RULES:';

function errMessage(err: unknown): string {
  if (err instanceof ServiceError) return err.message;
  if (err instanceof Error) return err.message;
  return 'Something went wrong';
}

function sortDimensions(dims: PersonaDimension[]): PersonaDimension[] {
  return [...dims].sort((a, b) => {
    const ia = DIMENSION_ORDER.indexOf(a.key);
    const ib = DIMENSION_ORDER.indexOf(b.key);
    return (ia === -1 ? Number.MAX_SAFE_INTEGER : ia) - (ib === -1 ? Number.MAX_SAFE_INTEGER : ib);
  });
}

// Recompose persona text from edited dimensions, preserving the guardrails tail
// of the previous text. Mirrors intake-core compose_persona's body format
// ("{Label}: {value}" lines) so the runtime prompt stays consistent.
function recomposePersonaText(dimensions: PersonaDimension[], prevText: string): string {
  const ordered = sortDimensions(dimensions.filter((d) => d.key !== 'guardrails'));
  const body = ordered.map((d) => `${DIMENSION_LABELS[d.key] ?? d.key}: ${d.value}`).join('\n');
  const guardIdx = prevText.indexOf(GUARDRAILS_MARKER);
  const tail = guardIdx >= 0 ? prevText.slice(guardIdx) : '';
  return tail ? `${body}\n\n${tail}` : body;
}

// Build a question card model from a draft question (re-uses ScreeningQuestionCard).
function withOrder(questions: ScreeningQuestion[]): ScreeningQuestion[] {
  return questions.map((q, i) => ({ ...q, orderIndex: i }));
}

export function IntakeScreeningPanel({
  id,
  sessionId,
  round,
  screening,
  onChange,
  onClose,
}: IntakeScreeningPanelProps) {
  const { showToast } = useToast();
  const panelRef = useRef<HTMLElement>(null);
  const [generating, setGenerating] = useState(false);
  const [deriving, setDeriving] = useState(false);

  useFocusTrap(panelRef, true, onClose);

  const enabled = screening?.enabled === true;
  const questions = screening?.questions ?? [];
  const persona = screening?.personaSnapshot;
  const dimensions = useMemo(() => persona?.dimensions ?? [], [persona]);
  const orderedDimensions = useMemo(() => sortDimensions(dimensions), [dimensions]);

  // Patch the current screening object, defaulting the unset fields when none
  // exists yet (so the first edit produces a complete object).
  const patch = useCallback(
    (next: Partial<RoundScreening>): RoundScreening => {
      const base: RoundScreening = screening ?? {
        enabled: false,
        voice: DEFAULT_VOICE,
        followUpStyle: DEFAULT_FOLLOW_UP,
        validityDays: DEFAULT_VALIDITY_DAYS,
        questions: [],
      };
      return { ...base, ...next };
    },
    [screening],
  );

  const dimensionValue = useCallback(
    (key: string): string => dimensions.find((d) => d.key === key)?.value ?? '',
    [dimensions],
  );

  const handleGenerate = useCallback(async () => {
    if (generating) return;
    setGenerating(true);
    try {
      const drafted = await generateScreeningDraft(sessionId, {
        roundName: round.name,
        category: round.category,
        skills: round.skills,
      });
      onChange(patch({ questions: withOrder(drafted) }));
      showToast(
        `Generated ${drafted.length} screening question${drafted.length === 1 ? '' : 's'}.`,
        'success',
      );
    } catch (err) {
      showToast(`Could not generate questions: ${errMessage(err)}`, 'error');
    } finally {
      setGenerating(false);
    }
  }, [generating, sessionId, round.name, round.category, round.skills, onChange, patch, showToast]);

  const handleDerive = useCallback(async () => {
    if (deriving) return;
    setDeriving(true);
    try {
      const derived = await derivePersonaDraft(sessionId);
      onChange(patch({ personaSnapshot: derived.snapshot }));
    } catch (err) {
      showToast(`Could not derive persona: ${errMessage(err)}`, 'error');
    } finally {
      setDeriving(false);
    }
  }, [deriving, sessionId, onChange, patch, showToast]);

  const updateQuestion = useCallback(
    (index: number, next: ScreeningQuestion) => {
      onChange(patch({ questions: questions.map((q, i) => (i === index ? next : q)) }));
    },
    [questions, onChange, patch],
  );

  const removeQuestion = useCallback(
    (index: number) => {
      onChange(patch({ questions: withOrder(questions.filter((_, i) => i !== index)) }));
    },
    [questions, onChange, patch],
  );

  // Edit a persona dimension value: flip source → recruiter, recompose text.
  const updateDimensionValue = useCallback(
    (key: string, value: string) => {
      if (!persona) return;
      const nextDims = dimensions.map((d) =>
        d.key === key ? { ...d, value, source: 'recruiter' as PersonaSource } : d,
      );
      onChange(
        patch({
          personaSnapshot: {
            dimensions: nextDims,
            text: recomposePersonaText(nextDims, persona.text),
          },
        }),
      );
    },
    [persona, dimensions, onChange, patch],
  );

  const toggleEnabled = useCallback(() => {
    onChange(patch({ enabled: !enabled }));
  }, [enabled, onChange, patch]);

  const questionCount = questions.length;
  const estMinutes = questions.reduce((s, q) => s + (q.durationMinutes || 0), 0);

  return (
    <div id={id} className="fixed inset-0 z-[60] flex justify-end bg-black/30" role="presentation">
      <button
        id={`${id}-scrim`}
        type="button"
        aria-label="Close screening config"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-transparent"
      />
      <aside
        ref={panelRef}
        id={`${id}-panel`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        className="relative flex h-full w-full max-w-[720px] flex-col overflow-hidden border-border border-l bg-white shadow-[0_0_80px_rgba(0,0,0,0.2)]"
      >
        <header className="flex items-start justify-between gap-4 border-border border-b px-5 py-4">
          <div className="flex min-w-0 items-start gap-2.5">
            <span
              aria-hidden
              className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-cortex-500/10 text-cortex-500"
            >
              <Sparkles strokeWidth={1.75} className="h-3.5 w-3.5" />
            </span>
            <div className="min-w-0">
              <h2
                id={`${id}-title`}
                className="font-display text-[20px] text-text-primary leading-tight tracking-[-0.005em]"
              >
                Screening Agent · Config
              </h2>
              <p id={`${id}-subtitle`} className="mt-0.5 text-[12.5px] text-text-muted">
                Round {round.round_number} · {round.name} · {questionCount} question
                {questionCount === 1 ? '' : 's'} · {estMinutes} min est
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              id={`${id}-enable`}
              type="button"
              onClick={toggleEnabled}
              aria-pressed={enabled}
              className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 font-medium font-sans text-[12.5px] transition ${
                enabled
                  ? 'border border-border bg-white text-text-primary hover:border-[#B91C1C] hover:text-[#B91C1C]'
                  : 'bg-text-primary text-bg hover:opacity-90'
              }`}
            >
              <Check strokeWidth={2} className="h-3.5 w-3.5" />
              {enabled ? 'OpenRecruiting takes this round · Remove' : 'OpenRecruiting takes this round'}
            </button>
            <button
              id={`${id}-close`}
              type="button"
              aria-label="Close"
              onClick={onClose}
              className="flex h-8 w-8 items-center justify-center rounded-full text-text-muted hover:bg-surface hover:text-text-primary"
            >
              <X strokeWidth={1.75} className="h-4 w-4" />
            </button>
          </div>
        </header>

        <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto px-5 py-5">
          {/* Summary bar */}
          <section
            id={`${id}-summary`}
            className="grid grid-cols-2 gap-px overflow-hidden rounded-[12px] border border-border bg-border sm:grid-cols-3"
          >
            <SummaryCell id={`${id}-summary-voice`} label="Voice">
              <select
                id={`${id}-summary-voice-select`}
                aria-label="Voice"
                value={screening?.voice ?? VOICE_OPTIONS[0]}
                onChange={(e) => onChange(patch({ voice: e.target.value }))}
                className="w-full bg-transparent font-medium font-sans text-[13px] text-text-primary outline-none"
              >
                {screening && !VOICE_OPTIONS.includes(screening.voice) && (
                  <option value={screening.voice}>{screening.voice}</option>
                )}
                {VOICE_OPTIONS.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </SummaryCell>
            <SummaryCell id={`${id}-summary-followup`} label="Follow-up style">
              <select
                id={`${id}-summary-followup-select`}
                aria-label="Follow-up style"
                value={screening?.followUpStyle ?? FOLLOW_UP_OPTIONS[0]}
                onChange={(e) => onChange(patch({ followUpStyle: e.target.value }))}
                className="w-full bg-transparent font-medium font-sans text-[13px] text-text-primary outline-none"
              >
                {screening && !FOLLOW_UP_OPTIONS.includes(screening.followUpStyle) && (
                  <option value={screening.followUpStyle}>{screening.followUpStyle}</option>
                )}
                {FOLLOW_UP_OPTIONS.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </SummaryCell>
            <SummaryCell id={`${id}-summary-validity`} label="Link valid for">
              <span className="inline-flex items-center gap-1 font-medium font-sans text-[13px] text-text-primary">
                <input
                  id={`${id}-summary-validity-input`}
                  type="number"
                  min={1}
                  max={90}
                  aria-label="Link validity in days"
                  value={screening?.validityDays ?? DEFAULT_VALIDITY_DAYS}
                  onChange={(e) =>
                    onChange(
                      patch({ validityDays: Number(e.target.value) || DEFAULT_VALIDITY_DAYS }),
                    )
                  }
                  className="w-12 bg-transparent outline-none"
                />
                days
              </span>
            </SummaryCell>
          </section>

          {/* Questions */}
          <section id={`${id}-questions`} className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
                Questions · {questionCount}
              </span>
              <button
                id={`${id}-generate`}
                type="button"
                disabled={generating}
                onClick={handleGenerate}
                className="inline-flex items-center gap-1.5 rounded-full border border-cortex-500/40 bg-cortex-500/5 px-3 py-1 font-medium font-mono text-[10.5px] text-cortex-500 uppercase tracking-[0.14em] transition hover:bg-cortex-500/10 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {generating ? (
                  <Loader2 strokeWidth={2} className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Sparkles strokeWidth={1.75} className="h-3.5 w-3.5" />
                )}
                {generating ? 'Generating…' : 'Generate questions'}
              </button>
            </div>

            {questionCount === 0 ? (
              <div
                id={`${id}-empty`}
                className="rounded-[12px] border border-border border-dashed bg-surface/40 p-6 text-center text-[13px] text-text-muted"
              >
                No screening questions yet. Generate a draft from this round's plan, then edit.
              </div>
            ) : (
              <div className="flex flex-col gap-2.5">
                {questions.map((q, i) => (
                  <ScreeningQuestionCard
                    key={q.id ?? `draft-${i}`}
                    id={`${id}-q-${i}`}
                    index={i}
                    question={q}
                    onChange={(next) => updateQuestion(i, next)}
                    onRemove={() => removeQuestion(i)}
                  />
                ))}
              </div>
            )}
          </section>

          {/* Interviewer persona (draft) */}
          <section id={`${id}-persona`} className="flex flex-col gap-3 border-border border-t pt-5">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
                Interviewer persona
              </span>
              <button
                id={`${id}-derive`}
                type="button"
                disabled={deriving}
                onClick={handleDerive}
                className="inline-flex items-center gap-1.5 rounded-full border border-cortex-500/40 bg-cortex-500/5 px-3 py-1 font-medium font-mono text-[10.5px] text-cortex-500 uppercase tracking-[0.14em] transition hover:bg-cortex-500/10 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {deriving ? (
                  <Loader2 strokeWidth={2} className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Sparkles strokeWidth={1.75} className="h-3.5 w-3.5" />
                )}
                {deriving ? 'Deriving…' : 'Derive from Cortex'}
              </button>
            </div>

            {!persona || orderedDimensions.length === 0 ? (
              <div
                id={`${id}-persona-empty`}
                className="rounded-[12px] border border-border border-dashed bg-surface/40 p-6 text-center text-[13px] text-text-muted"
              >
                No persona yet — derive it from your team's interview history.
              </div>
            ) : (
              <>
                <PersonaToneKnobs
                  id={`${id}-tone-knobs`}
                  toneValue={dimensionValue('tone_rapport')}
                  probingValue={dimensionValue('probing_depth')}
                  onApply={updateDimensionValue}
                />
                <div className="flex flex-col gap-2.5">
                  {orderedDimensions.map((dim) => (
                    <DraftDimensionCard
                      key={dim.key}
                      id={`${id}-dim-${dim.key}`}
                      dimension={dim}
                      onChange={(value) => updateDimensionValue(dim.key, value)}
                    />
                  ))}
                </div>
              </>
            )}
          </section>

          <p id={`${id}-foot-hint`} className="text-[11.5px] text-text-faint italic">
            Saved with the plan when you publish. No candidates are invited until then.
          </p>
        </div>

        <footer className="flex items-center justify-end gap-2 border-border border-t px-5 py-3">
          <button
            id={`${id}-done`}
            type="button"
            onClick={onClose}
            className="inline-flex items-center gap-1.5 rounded-full border border-text-primary bg-text-primary px-4 py-1.5 font-medium font-sans text-[12.5px] text-bg transition hover:opacity-90"
          >
            <Check strokeWidth={2} className="h-3.5 w-3.5" />
            Done
          </button>
        </footer>
      </aside>
    </div>
  );
}

function SummaryCell({
  id,
  label,
  children,
}: {
  id: string;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div id={id} className="flex flex-col gap-1 bg-white px-3.5 py-3">
      <span className="font-mono text-[9.5px] text-text-faint uppercase tracking-[0.14em]">
        {label}
      </span>
      {children}
    </div>
  );
}

function sourceBadgeClass(source: PersonaSource): string {
  if (source === 'cortex') return 'border-cortex-500/40 bg-cortex-500/5 text-cortex-500';
  if (source === 'recruiter') return 'border-text-primary/30 bg-surface text-text-primary';
  return 'border-border bg-surface/60 text-text-muted';
}

function DraftDimensionCard({
  id,
  dimension,
  onChange,
}: {
  id: string;
  dimension: PersonaDimension;
  onChange: (value: string) => void;
}) {
  const pct = Math.round(Math.max(0, Math.min(1, dimension.confidence)) * 100);
  return (
    <article
      id={id}
      className="rounded-[12px] border border-cortex-500/25 bg-white p-4 shadow-[0_1px_2px_rgba(0,0,0,0.02)]"
    >
      <header className="flex items-start justify-between gap-2">
        <span
          id={`${id}-label`}
          className="font-medium font-mono text-[11px] text-cortex-500 uppercase tracking-[0.16em]"
        >
          {DIMENSION_LABELS[dimension.key] ?? dimension.key}
        </span>
        <span
          id={`${id}-source`}
          className={`inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 font-medium font-mono text-[9px] uppercase tracking-[0.14em] ${sourceBadgeClass(
            dimension.source,
          )}`}
        >
          {SOURCE_LABELS[dimension.source] ?? dimension.source}
        </span>
      </header>
      <label className="mt-3 flex flex-col gap-1" htmlFor={`${id}-value`}>
        <span className="font-mono text-[9.5px] text-text-faint uppercase tracking-[0.14em]">
          Guidance
        </span>
        <textarea
          id={`${id}-value`}
          value={dimension.value}
          onChange={(e) => onChange(e.target.value)}
          rows={2}
          className="resize-y rounded-[8px] border border-border bg-white px-2.5 py-1.5 text-[13px] text-text-primary focus:border-cortex-500 focus:outline-none"
        />
      </label>
      <div
        id={`${id}-confidence`}
        className="mt-3 flex items-center gap-2 border-border border-t pt-2.5"
      >
        <span className="font-mono text-[9.5px] text-text-faint uppercase tracking-[0.14em]">
          Confidence
        </span>
        <span
          id={`${id}-confidence-bar`}
          aria-hidden
          className="h-1 flex-1 overflow-hidden rounded-full bg-border"
        >
          <span className="block h-full rounded-full bg-cortex-500" style={{ width: `${pct}%` }} />
        </span>
        <span className="font-medium font-mono text-[10px] text-text-primary tabular-nums">
          {pct}%
        </span>
      </div>
    </article>
  );
}
