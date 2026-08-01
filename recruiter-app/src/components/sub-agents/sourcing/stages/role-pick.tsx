'use client';

import { ReqPickGrid } from '@/components/pickers';
import { cancelFreshQuery, pickRoleForSourcing } from '../flow';

interface RolePickStageProps {
  id: string;
}

/**
 * Role pick has no visible agent message — the greeting streams via
 * runSourcingStage('role_pick') into session.messages, which TranscriptTail
 * renders above this component. This stage only attaches the role-picker
 * UX + a "back" affordance.
 */
export function RolePickStage({ id }: RolePickStageProps) {
  return (
    <div id={id} className="flex flex-col gap-6 pt-2">
      <ReqPickGrid
        id={`${id}-picker`}
        onPick={(role) => {
          void pickRoleForSourcing(role);
        }}
      />
      <button
        id={`${id}-back`}
        type="button"
        onClick={cancelFreshQuery}
        className="inline-flex w-fit items-center gap-1.5 font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em] hover:text-text-primary"
      >
        Back to mode choice
      </button>
    </div>
  );
}
