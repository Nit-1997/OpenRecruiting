'use client';

import { ArrowRight, Check, Sparkles } from 'lucide-react';
import { useMemo, useState } from 'react';
import {
  countCriteria,
  parseQuery,
  SOURCING_CRITERIA_LABELS,
  type SourcingCriteria,
  TRY_QUERIES,
} from '@/fixtures/sourcing-queries';
import { cn } from '@/lib/utils';

interface SourcingComposerProps {
  id: string;
  onSubmit: (text: string) => void;
  onTryQuery?: (query: string) => void;
  initialValue?: string;
  placeholder?: string;
}

const CRITERIA_ORDER: (keyof SourcingCriteria)[] = [
  'title',
  'location',
  'yoe',
  'industry',
  'skills',
];

export function SourcingComposer({
  id,
  onSubmit,
  onTryQuery,
  initialValue = '',
  placeholder = 'Staff PMs in Sunnyvale with 7 years of experience in growth using Product Analytics...',
}: SourcingComposerProps) {
  const [value, setValue] = useState(initialValue);
  const criteria = useMemo(() => parseQuery(value), [value]);
  const count = countCriteria(criteria);
  const canSubmit = count >= 1 && value.trim().length > 0;

  const submit = () => {
    if (!canSubmit) return;
    onSubmit(value.trim());
  };

  return (
    <div id={id} className="flex w-full max-w-[760px] flex-col gap-4">
      <div
        id={`${id}-field-wrap`}
        className="flex items-center gap-2 rounded-[20px] border border-border bg-white px-4 py-3 shadow-[0_8px_24px_rgba(0,0,0,0.04)] transition-colors focus-within:border-text-primary"
      >
        <Sparkles strokeWidth={1.75} className="h-4 w-4 shrink-0 text-text-muted" aria-hidden />
        <input
          id={`${id}-input`}
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && canSubmit) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={placeholder}
          className="flex-1 border-0 bg-transparent py-1 text-[14px] text-text-primary placeholder:text-text-muted focus:outline-none"
          aria-label="Describe who you are looking for"
        />
        <div
          id={`${id}-count`}
          className={cn(
            'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.14em]',
            count === 0
              ? 'border-border bg-surface text-text-faint'
              : 'border-[#A7F3D0] bg-[#ECFDF5] text-[#047857]',
          )}
        >
          {count === 0 ? (
            <span>0/5 filters</span>
          ) : (
            <>
              <Check strokeWidth={2} className="h-3 w-3" aria-hidden />
              <span>
                {count}/5 filter{count === 1 ? '' : 's'}
              </span>
            </>
          )}
        </div>
        <button
          id={`${id}-send`}
          type="button"
          aria-label="Search"
          onClick={submit}
          disabled={!canSubmit}
          className={cn(
            'flex h-8 w-8 items-center justify-center rounded-full transition-colors',
            canSubmit
              ? 'bg-text-primary text-white hover:bg-[#222]'
              : 'bg-surface text-text-muted opacity-60',
          )}
        >
          <ArrowRight strokeWidth={1.75} className="h-4 w-4" />
        </button>
      </div>

      <FilterPreview id={`${id}-preview`} criteria={criteria} />

      <TryQueries
        id={`${id}-try`}
        onPick={(q) => {
          setValue(q);
          onTryQuery?.(q);
        }}
      />
    </div>
  );
}

function FilterPreview({ id, criteria }: { id: string; criteria: SourcingCriteria }) {
  const pills = CRITERIA_ORDER.map((key) => {
    const label = SOURCING_CRITERIA_LABELS[key];
    if (key === 'skills') {
      const skills = criteria.skills ?? [];
      return { key, label, active: skills.length > 0, value: skills.join(', ') };
    }
    const value = criteria[key] as string | undefined;
    return { key, label, active: Boolean(value), value: value ?? '' };
  });

  return (
    <div id={id} className="flex flex-wrap gap-2">
      {pills.map((p) => (
        <span
          key={p.key}
          id={`${id}-pill-${p.key}`}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-sans text-[12px] transition-colors',
            p.active
              ? 'border-[#A7F3D0] bg-[#ECFDF5] text-[#047857]'
              : 'border-border bg-white text-text-muted',
          )}
        >
          {p.active ? (
            <Check strokeWidth={2} className="h-3 w-3" aria-hidden />
          ) : (
            <span
              id={`${id}-pill-${p.key}-dot`}
              aria-hidden
              className="h-1.5 w-1.5 rounded-full bg-border"
            />
          )}
          <span
            id={`${id}-pill-${p.key}-label`}
            className="font-mono text-[10.5px] uppercase tracking-[0.12em]"
          >
            {p.label}
          </span>
          {p.active && (
            <span
              id={`${id}-pill-${p.key}-value`}
              className="font-medium font-sans text-[12px] text-text-primary"
            >
              {p.value}
            </span>
          )}
        </span>
      ))}
    </div>
  );
}

function TryQueries({ id, onPick }: { id: string; onPick: (q: string) => void }) {
  return (
    <div id={id} className="mt-1 flex flex-col gap-2">
      <div
        id={`${id}-eyebrow`}
        className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]"
      >
        Try these
      </div>
      <div id={`${id}-list`} className="flex flex-wrap gap-2">
        {TRY_QUERIES.map((q, i) => (
          <button
            // biome-ignore lint/suspicious/noArrayIndexKey: static list of 4
            key={i}
            id={`${id}-item-${i}`}
            type="button"
            onClick={() => onPick(q)}
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-white px-3 py-1.5 font-sans text-[12px] text-text-primary transition-colors hover:border-text-primary"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
