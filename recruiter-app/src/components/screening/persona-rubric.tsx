'use client';

import { Check, Loader2, Sparkles } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useToast } from '@/components/ui/toast';
import {
  derivePersona,
  getPersona,
  type Persona,
  type PersonaDimension,
  type PersonaSource,
  savePersona,
} from '@/services/screening';
import { ServiceError } from '@/services/service-error';
import { PersonaPicker } from './persona-picker';
import { PersonaToneKnobs } from './persona-tone-knobs';

export interface PersonaRubricProps {
  id: string;
  requisitionId: string;
  roundId: string;
}

// The 5 fixed persona dimensions + their human labels. Order here drives the
// render order so the rubric reads top-to-bottom regardless of server order.
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

function dimensionLabel(key: string): string {
  return DIMENSION_LABELS[key] ?? key;
}

function sortDimensions(dims: PersonaDimension[]): PersonaDimension[] {
  return [...dims].sort((a, b) => {
    const ia = DIMENSION_ORDER.indexOf(a.key);
    const ib = DIMENSION_ORDER.indexOf(b.key);
    // Unknown keys (ia/ib === -1) fall to the end, preserving their relative order.
    return (ia === -1 ? Number.MAX_SAFE_INTEGER : ia) - (ib === -1 ? Number.MAX_SAFE_INTEGER : ib);
  });
}

function errMessage(err: unknown): string {
  if (err instanceof ServiceError) return err.message;
  if (err instanceof Error) return err.message;
  return 'Something went wrong';
}

export function PersonaRubric({ id, requisitionId, roundId }: PersonaRubricProps) {
  const { showToast } = useToast();

  const [persona, setPersona] = useState<Persona | null>(null);
  const [loading, setLoading] = useState(true);
  const [deriving, setDeriving] = useState(false);
  const [saving, setSaving] = useState(false);

  // getPersona returns an empty persona (personaId === null, no dimensions)
  // when nothing is attached yet — we treat that as "no persona" for the empty
  // state.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getPersona(requisitionId, roundId)
      .then((loaded) => {
        if (cancelled) return;
        setPersona(loaded.dimensions.length > 0 ? loaded : null);
      })
      .catch((err) => {
        if (cancelled) return;
        showToast(`Could not load interviewer persona: ${errMessage(err)}`, 'error');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [requisitionId, roundId, showToast]);

  const handleDerive = useCallback(async () => {
    if (deriving) return;
    setDeriving(true);
    try {
      const derived = await derivePersona(requisitionId, roundId);
      setPersona(derived);
    } catch (err) {
      showToast(`Could not derive persona: ${errMessage(err)}`, 'error');
    } finally {
      setDeriving(false);
    }
  }, [deriving, requisitionId, roundId, showToast]);

  // Editing a value flips that dimension's source to `recruiter` so the saved
  // rubric (and the source badge) reflect the manual edit.
  const updateDimensionValue = useCallback((key: string, value: string) => {
    setPersona((curr) => {
      if (!curr) return curr;
      const dimensions = curr.dimensions.map((d) =>
        d.key === key ? { ...d, value, source: 'recruiter' as PersonaSource } : d,
      );
      return { ...curr, dimensions };
    });
  }, []);

  const handleSave = useCallback(async () => {
    if (!persona || saving) return;
    setSaving(true);
    try {
      const saved = await savePersona(requisitionId, roundId, {
        dimensions: persona.dimensions,
      });
      setPersona(saved);
      showToast('Interviewer persona saved.', 'success');
    } catch (err) {
      showToast(`Could not save persona: ${errMessage(err)}`, 'error');
    } finally {
      setSaving(false);
    }
  }, [persona, saving, requisitionId, roundId, showToast]);

  const orderedDimensions = useMemo(
    () => (persona ? sortDimensions(persona.dimensions) : []),
    [persona],
  );

  const dimensionValue = useCallback(
    (key: string): string => persona?.dimensions.find((d) => d.key === key)?.value ?? '',
    [persona],
  );

  return (
    <section id={id} className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]">
          Interviewer persona
        </span>
        <div className="flex items-center gap-2">
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
      </div>

      <PersonaPicker
        id={`${id}-picker`}
        requisitionId={requisitionId}
        roundId={roundId}
        currentDimensions={persona?.dimensions ?? []}
        onApplied={(applied) => setPersona(applied.dimensions.length > 0 ? applied : null)}
      />

      {loading ? (
        <p id={`${id}-loading`} className="text-[13px] text-text-muted">
          Loading interviewer persona…
        </p>
      ) : !persona ? (
        <div
          id={`${id}-empty`}
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
              <PersonaDimensionCard
                key={dim.key}
                id={`${id}-dim-${dim.key}`}
                dimension={dim}
                onChange={(value) => updateDimensionValue(dim.key, value)}
              />
            ))}
          </div>

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
              {saving ? 'Saving…' : 'Save persona'}
            </button>
          </div>
        </>
      )}
    </section>
  );
}

function sourceBadgeClass(source: PersonaSource): string {
  if (source === 'cortex') return 'border-cortex-500/40 bg-cortex-500/5 text-cortex-500';
  if (source === 'recruiter') return 'border-text-primary/30 bg-surface text-text-primary';
  return 'border-border bg-surface/60 text-text-muted';
}

function PersonaDimensionCard({
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
          {dimensionLabel(dimension.key)}
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
