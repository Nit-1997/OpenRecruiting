'use client';

import type { ProcessStage, ProcessStageStatus } from '@/types/intake';

interface Props {
  id: string;
  stages: ProcessStage[];
}

const PREFILL_ORDER: Array<ProcessStage['name']> = [
  'check_context',
  'parse_jd',
  'query_cortex',
  'synthesize',
];

const LABELS: Record<ProcessStage['name'], string> = {
  check_context: 'Checking your history',
  parse_jd: 'Reading the job description',
  query_cortex: 'Pulling context from past roles',
  synthesize: 'Drafting initial answers',
  scorecard_rounds: 'Designing rounds',
  scorecard_details: 'Filling in details',
};

function icon(status: ProcessStageStatus): string {
  if (status === 'completed') return '[done]';
  if (status === 'running') return '[...]';
  if (status === 'failed') return '[x]';
  return '[ ]';
}

export function PrefillProgress({ id, stages }: Props) {
  const map = new Map(stages.map((s) => [s.name, s]));
  return (
    <div id={id} className="space-y-2">
      <h3
        id={`${id}-title`}
        className="text-[var(--text-muted)] text-xs uppercase tracking-wide"
        style={{ fontFamily: 'var(--font-mono)' }}
      >
        Preparing your intake
      </h3>
      <ul id={`${id}-list`} className="space-y-1 text-sm">
        {PREFILL_ORDER.map((name) => {
          const stage = map.get(name);
          const status: ProcessStageStatus = stage?.status ?? 'pending';
          return (
            <li
              id={`${id}-row-${name}`}
              key={name}
              data-status={status}
              className={`flex items-baseline gap-2 ${
                status === 'completed'
                  ? 'text-emerald-700'
                  : status === 'running'
                    ? 'text-[var(--cortex-600)]'
                    : status === 'failed'
                      ? 'text-red-600'
                      : 'text-[var(--text-muted)]'
              }`}
            >
              <span className="shrink-0 font-mono text-xs" style={{ minWidth: '3.5rem' }}>
                {icon(status)}
              </span>
              {LABELS[name] ?? name}
              {status === 'failed' && stage?.error && (
                <span id={`${id}-error-${name}`} className="ml-2 text-red-600 text-xs italic">
                  — {stage.error}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
