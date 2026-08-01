'use client';

import { Check } from 'lucide-react';
import type { IntakeSession, ProcessStage, ProcessStageStatus } from '@/types/intake';
import { Orb } from '../primitives';

interface Props {
  id: string;
  session: IntakeSession;
}

const PREFILL_STEP_NAMES: Array<ProcessStage['name']> = [
  'check_context',
  'parse_jd',
  'query_cortex',
  'synthesize',
];

const STEP_LABELS: Partial<Record<ProcessStage['name'], string>> = {
  check_context: 'Reading your context',
  parse_jd: 'Parsing the job description',
  query_cortex: 'Pulling comparable roles from Cortex',
  synthesize: 'Drafting the 9 intake goals',
};

function toDataState(status: ProcessStageStatus): 'done' | 'run' | 'wait' {
  if (status === 'completed') return 'done';
  if (status === 'running') return 'run';
  return 'wait';
}

export function PrefillingStage({ id, session }: Props) {
  const stageMap = new Map(session.process_stages.map((s) => [s.name, s]));
  const roleName = session.form_data.role_name || 'Your role';

  const visibleSteps = PREFILL_STEP_NAMES.filter((name) => stageMap.has(name));

  return (
    <div id={id} className="mz-gather">
      <div id={`${id}-card`} className="mz-gather-card">
        <Orb size={104} state="connecting" />

        <p id={`${id}-eyebrow`} className="mz-eyebrow" style={{ marginTop: '24px' }}>
          Gathering context
        </p>

        <h2 id={`${id}-title`} className="mz-gather-title">
          {roleName}
        </h2>

        <ul id={`${id}-steps`} className="mz-gather-steps">
          {visibleSteps.map((name) => {
            const stage = stageMap.get(name);
            const dataState = toDataState(stage?.status ?? 'pending');
            return (
              <li id={`${id}-step-${name}`} key={name} data-state={dataState}>
                <span className="mz-gather-mark">
                  {dataState === 'done' && <Check size={12} color="#fff" strokeWidth={3} />}
                </span>
                {STEP_LABELS[name] ?? name}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
