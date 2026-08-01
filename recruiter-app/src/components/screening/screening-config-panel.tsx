'use client';

import { Check, Loader2, Sparkles, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useToast } from '@/components/ui/toast';
import { useFocusTrap } from '@/hooks/use-focus-trap';
import {
  generateScreening,
  getScreening,
  inviteScreening,
  type ScreeningConfig,
  type ScreeningQuestion,
  saveScreening,
} from '@/services/screening';
import { ServiceError } from '@/services/service-error';
import type { Round } from '@/types';
import { PersonaRubric } from './persona-rubric';
import { ScreeningInviteForm } from './screening-invite-form';
import { ScreeningQuestionCard } from './screening-question-card';

export interface ScreeningConfigPanelProps {
  id: string;
  requisitionId: string;
  roundId: string;
  round: Round;
  onClose: () => void;
}

// Voice + follow-up options offered in the summary bar. The backend stores
// these as free text, so these are conventional presets — the recruiter can
// also keep whatever a generated draft returned (added as an option below).
const VOICE_OPTIONS = ['Aura · "Luna"', 'Aura · "Orion"', 'Aura · "Stella"'];
const FOLLOW_UP_OPTIONS = ['Adaptive probes', 'Fixed script', 'Light touch'];

const DEPLOY_SCOPE_LABELS: Record<string, string> = {
  all_resume_passed: 'All resume-passed',
};

function deployScopeLabel(scope: string): string {
  return DEPLOY_SCOPE_LABELS[scope] ?? scope;
}

function errMessage(err: unknown): string {
  if (err instanceof ServiceError) return err.message;
  if (err instanceof Error) return err.message;
  return 'Something went wrong';
}

function estMinutes(config: ScreeningConfig): number {
  const summed = config.questions.reduce((s, q) => s + (q.durationMinutes || 0), 0);
  return summed > 0 ? summed : (config.estDurationMinutes ?? 0);
}

export function ScreeningConfigPanel({
  id,
  requisitionId,
  roundId,
  round,
  onClose,
}: ScreeningConfigPanelProps) {
  const { showToast } = useToast();
  const panelRef = useRef<HTMLElement>(null);

  const [config, setConfig] = useState<ScreeningConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [attaching, setAttaching] = useState(false);
  const [inviting, setInviting] = useState(false);
  const [inviteResult, setInviteResult] = useState<{ count: number; validityDays: number } | null>(
    null,
  );

  useFocusTrap(panelRef, true, onClose);

  // Initial load. getScreening returns null when nothing is saved yet — we keep
  // config null so the empty state ("Generate questions") renders.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getScreening(requisitionId, roundId)
      .then((loaded) => {
        if (cancelled) return;
        setConfig(loaded);
      })
      .catch((err) => {
        if (cancelled) return;
        showToast(`Could not load screening config: ${errMessage(err)}`, 'error');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [requisitionId, roundId, showToast]);

  const handleGenerate = useCallback(async () => {
    if (generating) return;
    setGenerating(true);
    try {
      const draft = await generateScreening(requisitionId, roundId, {});
      setConfig(draft);
    } catch (err) {
      showToast(`Could not generate questions: ${errMessage(err)}`, 'error');
    } finally {
      setGenerating(false);
    }
  }, [generating, requisitionId, roundId, showToast]);

  const patchConfig = useCallback((patch: Partial<ScreeningConfig>) => {
    setConfig((curr) => (curr ? { ...curr, ...patch } : curr));
  }, []);

  const updateQuestion = useCallback((index: number, next: ScreeningQuestion) => {
    setConfig((curr) => {
      if (!curr) return curr;
      const questions = curr.questions.map((q, i) => (i === index ? next : q));
      return { ...curr, questions };
    });
  }, []);

  const removeQuestion = useCallback((index: number) => {
    setConfig((curr) => {
      if (!curr) return curr;
      const questions = curr.questions
        .filter((_, i) => i !== index)
        .map((q, i) => ({ ...q, orderIndex: i }));
      return { ...curr, questions };
    });
  }, []);

  const handleSave = useCallback(async () => {
    if (!config || saving) return;
    setSaving(true);
    try {
      const saved = await saveScreening(requisitionId, roundId, config);
      setConfig(saved);
      showToast('Screening config saved.', 'success');
    } catch (err) {
      showToast(`Could not save screening config: ${errMessage(err)}`, 'error');
    } finally {
      setSaving(false);
    }
  }, [config, saving, requisitionId, roundId, showToast]);

  const handleToggleAttach = useCallback(async () => {
    if (!config || attaching) return;
    setAttaching(true);
    try {
      // Persist the full config with the toggled `enabled` via saveScreening
      // (PUT → upsert RPC). attach/detach only flip `enabled` on an EXISTING
      // row; if the recruiter generated questions but never clicked Save, no
      // round_screening_configs row exists, so the flip updates 0 rows and the
      // backend returns null → configFromWire(null) threw a TypeError. Upserting
      // guarantees the row (with the generated questions) and a full response.
      const next = { ...config, enabled: !config.enabled };
      const saved = await saveScreening(requisitionId, roundId, next);
      setConfig(saved);
      showToast(
        saved.enabled ? 'Screening agent attached.' : 'Screening agent detached.',
        'success',
      );
    } catch (err) {
      showToast(`Could not update screening agent: ${errMessage(err)}`, 'error');
    } finally {
      setAttaching(false);
    }
  }, [config, attaching, requisitionId, roundId, showToast]);

  const handleInvite = useCallback(
    async ({ mode, emails }: { mode: 'emails' | 'scope'; emails: string[] }) => {
      if (!config || inviting) return;
      setInviting(true);
      try {
        const body = mode === 'emails' ? { emails } : { scope: config.deployScope };
        await inviteScreening(requisitionId, roundId, body);
        const count = mode === 'emails' ? emails.length : 0;
        setInviteResult({ count, validityDays: config.validityDays });
        showToast(
          mode === 'emails'
            ? `Invited ${count} candidate${count === 1 ? '' : 's'}.`
            : 'Screening invites sent.',
          'success',
        );
      } catch (err) {
        showToast(`Could not send invites: ${errMessage(err)}`, 'error');
      } finally {
        setInviting(false);
      }
    },
    [config, inviting, requisitionId, roundId, showToast],
  );

  const questionCount = config?.questions.length ?? 0;
  const est = config ? estMinutes(config) : 0;
  const subtitle = useMemo(
    () =>
      `Will run on Round ${round.roundNumber} · ${round.name} · ${questionCount} question${
        questionCount === 1 ? '' : 's'
      } · ${est} min est`,
    [round.roundNumber, round.name, questionCount, est],
  );

  return (
    <div id={id} className="fixed inset-0 z-50 flex justify-end bg-black/30" role="presentation">
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
                {subtitle}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              id={`${id}-attach`}
              type="button"
              disabled={!config || attaching}
              onClick={handleToggleAttach}
              className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 font-medium font-sans text-[12.5px] transition disabled:cursor-not-allowed disabled:opacity-40 ${
                config?.enabled
                  ? 'border border-border bg-white text-text-primary hover:border-[#B91C1C] hover:text-[#B91C1C]'
                  : 'bg-text-primary text-bg hover:opacity-90'
              }`}
            >
              {attaching ? (
                <Loader2 strokeWidth={2} className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Check strokeWidth={2} className="h-3.5 w-3.5" />
              )}
              {config?.enabled ? 'Attached · Detach' : 'Attach screening agent'}
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
            className="grid grid-cols-2 gap-px overflow-hidden rounded-[12px] border border-border bg-border sm:grid-cols-4"
          >
            <SummaryCell id={`${id}-summary-voice`} label="Voice">
              <select
                id={`${id}-summary-voice-select`}
                aria-label="Voice"
                value={config?.voice ?? ''}
                disabled={!config}
                onChange={(e) => patchConfig({ voice: e.target.value })}
                className="w-full bg-transparent font-medium font-sans text-[13px] text-text-primary outline-none disabled:opacity-50"
              >
                {config && !VOICE_OPTIONS.includes(config.voice) && (
                  <option value={config.voice}>{config.voice}</option>
                )}
                {VOICE_OPTIONS.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </SummaryCell>
            <SummaryCell id={`${id}-summary-duration`} label="Est. duration">
              <span className="inline-flex items-center gap-1 font-medium font-sans text-[13px] text-text-primary">
                <input
                  id={`${id}-summary-duration-input`}
                  type="number"
                  min={1}
                  max={120}
                  aria-label="Estimated duration in minutes"
                  value={config?.estDurationMinutes ?? 0}
                  disabled={!config}
                  onChange={(e) => patchConfig({ estDurationMinutes: Number(e.target.value) || 0 })}
                  className="w-12 bg-transparent outline-none disabled:opacity-50"
                />
                min
              </span>
            </SummaryCell>
            <SummaryCell id={`${id}-summary-followup`} label="Follow-up style">
              <select
                id={`${id}-summary-followup-select`}
                aria-label="Follow-up style"
                value={config?.followUpStyle ?? ''}
                disabled={!config}
                onChange={(e) => patchConfig({ followUpStyle: e.target.value })}
                className="w-full bg-transparent font-medium font-sans text-[13px] text-text-primary outline-none disabled:opacity-50"
              >
                {config && !FOLLOW_UP_OPTIONS.includes(config.followUpStyle) && (
                  <option value={config.followUpStyle}>{config.followUpStyle}</option>
                )}
                {FOLLOW_UP_OPTIONS.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </SummaryCell>
            <SummaryCell id={`${id}-summary-deploy`} label="Deploy to">
              <span className="font-medium font-sans text-[13px] text-text-primary">
                {config ? deployScopeLabel(config.deployScope) : '—'}
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

            {loading ? (
              <p id={`${id}-loading`} className="text-[13px] text-text-muted">
                Loading screening config…
              </p>
            ) : !config || config.questions.length === 0 ? (
              <div
                id={`${id}-empty`}
                className="rounded-[12px] border border-border border-dashed bg-surface/40 p-6 text-center text-[13px] text-text-muted"
              >
                No screening questions yet. Generate a draft from this round's plan, then edit.
              </div>
            ) : (
              <div className="flex flex-col gap-2.5">
                {config.questions.map((q, i) => (
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

            {config && config.questions.length > 0 && (
              <div className="flex justify-end">
                <button
                  id={`${id}-save`}
                  type="button"
                  disabled={saving}
                  onClick={handleSave}
                  className="inline-flex items-center gap-1.5 rounded-full border border-text-primary bg-text-primary px-3.5 py-1.5 font-medium font-sans text-[12.5px] text-bg transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {saving ? (
                    <Loader2 strokeWidth={2} className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Check strokeWidth={2} className="h-3.5 w-3.5" />
                  )}
                  {saving ? 'Saving…' : 'Save config'}
                </button>
              </div>
            )}
          </section>

          {/* Interviewer persona rubric */}
          <div className="border-border border-t pt-5">
            <PersonaRubric id={`${id}-persona`} requisitionId={requisitionId} roundId={roundId} />
          </div>

          {/* Invite */}
          {config && (
            <div className="border-border border-t pt-5">
              <ScreeningInviteForm
                id={`${id}-invite`}
                validityDays={config.validityDays}
                deployScopeLabel={deployScopeLabel(config.deployScope)}
                disabled={!config.enabled}
                busy={inviting}
                lastResult={inviteResult}
                onSend={handleInvite}
              />
              {!config.enabled && (
                <p id={`${id}-invite-gate`} className="mt-2 text-[11.5px] text-text-faint italic">
                  Attach the screening agent to this round before sending invites.
                </p>
              )}
            </div>
          )}
        </div>
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
