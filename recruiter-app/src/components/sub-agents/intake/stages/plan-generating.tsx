'use client';

import { Check } from 'lucide-react';
import type { JSX } from 'react';
import type { IntakeSession, ProcessStage, ProcessStageStatus } from '@/types/intake';
import { Orb } from '../primitives';

const BUILD_STEP_NAMES: Array<ProcessStage['name']> = ['scorecard_rounds', 'scorecard_details'];

const LABELS: Partial<Record<ProcessStage['name'], string>> = {
  scorecard_rounds: 'Structuring interview rounds',
  scorecard_details: 'Drafting rubrics & guidelines',
};

function toDataState(status: ProcessStageStatus): 'done' | 'run' | 'wait' {
  if (status === 'completed') return 'done';
  if (status === 'running') return 'run';
  return 'wait';
}

interface Props {
  session: IntakeSession;
}

export function PlanGenerating({ session }: Props): JSX.Element {
  const byName = new Map(session.process_stages.map((s) => [s.name, s]));
  const roleName = session.form_data.role_name || 'Your role';

  const completed = BUILD_STEP_NAMES.filter((n) => byName.get(n)?.status === 'completed').length;
  const pct = Math.max(6, Math.round((completed / BUILD_STEP_NAMES.length) * 100));

  return (
    <div id="intake-stage-plan-generating" className="mz-gather">
      <div id="intake-stage-plan-generating-card" className="mz-gather-card mz-build-card">
        <Orb size={104} state="connecting" />
        <p className="mz-eyebrow" style={{ marginTop: '24px' }}>
          Building interview plan
        </p>
        <h2 className="mz-gather-title">{roleName}</h2>
        <div id="intake-stage-plan-generating-bar" className="mz-build-bar">
          <span style={{ width: `${pct}%` }} />
        </div>
        <div className="mz-build-pct">{pct}%</div>
        <ul id="intake-stage-plan-generating-stages" className="mz-gather-steps">
          {BUILD_STEP_NAMES.map((name) => {
            const status = byName.get(name)?.status ?? 'pending';
            const dataState = toDataState(status);
            return (
              <li
                id={`intake-stage-plan-generating-step-${name}`}
                key={name}
                data-state={dataState}
              >
                <span className="mz-gather-mark">
                  {dataState === 'done' && <Check size={12} color="#fff" strokeWidth={3} />}
                </span>
                {LABELS[name] ?? name}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
