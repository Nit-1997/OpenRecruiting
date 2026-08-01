'use client';

import { useEffect, useRef, useState } from 'react';
import { ReqPickGrid } from '@/components/pickers';
import type { RoleFixture } from '@/fixtures/roles';
import { listRoles, roleItemToFixture } from '@/lib/debrief/api';
import { isV2ApiEnabled } from '@/lib/env';
import { useSessionStore } from '@/stores';
import { pickDebriefRole, runDebriefStage } from '../flow';

interface RolePickStageProps {
  id: string;
}

/**
 * Role pick stage has no visible agent message — the greeting streams via
 * runDebriefStage('role_pick') into session.messages, which TranscriptTail
 * renders above this component. This stage only attaches the role-picker UX
 * under the latest agent bubble, matching the Intake canvas pattern.
 *
 * Under v2 the role grid is backed by GET /api/v2/debrief/roles (roles with
 * >= 2 eligible candidates). The mock path keeps the REQS fixture (the grid's
 * default), so demo mode renders without a backend.
 */
export function RolePickStage({ id }: RolePickStageProps) {
  const session = useSessionStore((s) => s.sessions.debrief);
  const started = useRef(false);
  const [roles, setRoles] = useState<RoleFixture[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (started.current) return;
    if (session && session.messages.length === 0 && session.stage === 'role_pick') {
      started.current = true;
      void runDebriefStage('role_pick');
    }
  }, [session]);

  useEffect(() => {
    if (!isV2ApiEnabled()) return;
    let active = true;
    listRoles()
      .then((items) => {
        if (active) setRoles(items.map(roleItemToFixture));
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : 'Failed to load roles.');
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div id={id} className="pt-4">
      {error ? (
        <div id={`${id}-error`} className="text-[13px] text-text-muted">
          {error}
        </div>
      ) : (
        <ReqPickGrid
          id={`${id}-picker`}
          {...(roles ? { roles } : {})}
          onPick={(r) => {
            void pickDebriefRole(r);
          }}
        />
      )}
    </div>
  );
}
