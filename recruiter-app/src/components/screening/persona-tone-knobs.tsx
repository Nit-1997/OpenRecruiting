'use client';

// Lightweight recruiter "tone knobs" — a fast UX for nudging the two style
// dimensions (tone_rapport, probing_depth) without re-deriving from Cortex.
//
// Each knob is a 3-option segmented control that maps to a bounded preset
// PHRASE. Selecting an option calls `onApply(key, presetValue)`; the parent
// rubric writes that into the SAME dimensions state it saves (flipping source to
// recruiter), so the change rides along with the existing "Save persona" action.
// No new state model, no new endpoint.

import { cn } from '@/lib/utils';

/** Warmth → tone_rapport preset phrases. */
export const WARMTH_PRESETS = {
  formal:
    'Professional and measured; keeps a respectful, businesslike distance while staying courteous.',
  balanced:
    'Friendly and professional; warm enough to build rapport without losing focus on the evaluation.',
  warm: 'Warm, conversational, and encouraging; puts the candidate at ease while staying professional.',
} as const;

/** Probing depth → probing_depth preset phrases. */
export const PROBING_PRESETS = {
  light:
    'Takes answers largely at face value; asks at most one clarifying follow-up before moving on.',
  standard:
    'Asks one to two follow-ups on key answers to confirm understanding and surface concrete detail.',
  deep: 'Probes 2-3 layers deep on substantive answers; pushes for specifics and trade-offs.',
} as const;

type WarmthLevel = keyof typeof WARMTH_PRESETS;
type ProbingLevel = keyof typeof PROBING_PRESETS;

const WARMTH_LABELS: Record<WarmthLevel, string> = {
  formal: 'Formal',
  balanced: 'Balanced',
  warm: 'Warm',
};
const PROBING_LABELS: Record<ProbingLevel, string> = {
  light: 'Light',
  standard: 'Standard',
  deep: 'Deep',
};

export interface PersonaToneKnobsProps {
  id: string;
  /** Current tone_rapport dimension value (used to highlight the active knob). */
  toneValue: string;
  /** Current probing_depth dimension value. */
  probingValue: string;
  /** Apply a preset phrase to a dimension. key is tone_rapport | probing_depth. */
  onApply: (key: 'tone_rapport' | 'probing_depth', value: string) => void;
}

// Best-effort: match the current value to a preset; default to the middle option
// (Balanced / Standard) when it's a bespoke recruiter-written phrase.
function activeWarmth(value: string): WarmthLevel {
  const hit = (Object.keys(WARMTH_PRESETS) as WarmthLevel[]).find(
    (k) => WARMTH_PRESETS[k] === value,
  );
  return hit ?? 'balanced';
}
function activeProbing(value: string): ProbingLevel {
  const hit = (Object.keys(PROBING_PRESETS) as ProbingLevel[]).find(
    (k) => PROBING_PRESETS[k] === value,
  );
  return hit ?? 'standard';
}

export function PersonaToneKnobs({ id, toneValue, probingValue, onApply }: PersonaToneKnobsProps) {
  const warmth = activeWarmth(toneValue);
  const probing = activeProbing(probingValue);

  return (
    <div
      id={id}
      className="flex flex-col gap-3 rounded-[12px] border border-border bg-surface/40 p-3.5"
    >
      <span className="font-mono text-[9.5px] text-text-faint uppercase tracking-[0.14em]">
        Tone
      </span>

      <Knob
        id={`${id}-warmth`}
        label="Warmth"
        levels={Object.keys(WARMTH_PRESETS) as WarmthLevel[]}
        labels={WARMTH_LABELS}
        active={warmth}
        onSelect={(level) => onApply('tone_rapport', WARMTH_PRESETS[level])}
      />

      <Knob
        id={`${id}-probing`}
        label="Probing depth"
        levels={Object.keys(PROBING_PRESETS) as ProbingLevel[]}
        labels={PROBING_LABELS}
        active={probing}
        onSelect={(level) => onApply('probing_depth', PROBING_PRESETS[level])}
      />
    </div>
  );
}

function Knob<L extends string>({
  id,
  label,
  levels,
  labels,
  active,
  onSelect,
}: {
  id: string;
  label: string;
  levels: L[];
  labels: Record<L, string>;
  active: L;
  onSelect: (level: L) => void;
}) {
  return (
    <div id={id} className="flex items-center justify-between gap-3">
      <span
        id={`${id}-label`}
        className="font-mono text-[10px] text-text-muted uppercase tracking-[0.12em]"
      >
        {label}
      </span>
      <fieldset
        id={`${id}-options`}
        className="inline-flex rounded-full border border-border bg-white p-0.5"
      >
        <legend className="sr-only">{label}</legend>
        {levels.map((level) => {
          const selected = level === active;
          return (
            <button
              id={`${id}-${level}`}
              key={level}
              type="button"
              aria-pressed={selected}
              onClick={() => onSelect(level)}
              className={cn(
                'rounded-full px-3 py-1 font-medium font-sans text-[11.5px] transition',
                selected ? 'bg-text-primary text-bg' : 'text-text-secondary hover:bg-surface',
              )}
            >
              {labels[level]}
            </button>
          );
        })}
      </fieldset>
    </div>
  );
}
