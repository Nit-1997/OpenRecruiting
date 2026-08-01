'use client';

import { useEffect, useState } from 'react';
import { CandidatePicker } from '@/components/pickers';
import type { CandidateFixture } from '@/fixtures/candidates';
import { candidateItemToFixture, listCandidates } from '@/lib/debrief/api';
import { isV2ApiEnabled } from '@/lib/env';
import { useSessionStore } from '@/stores';
import { cancelCandidatePick, confirmCandidatePick, toggleCandidate } from '../flow';

interface CandidatePickStageProps {
  id: string;
}

/**
 * Candidate pick stage attaches the picker UX below the agent's "Got it —
 * <role>. Which candidates should I compare?" message, which is already
 * rendered by TranscriptTail above. No duplicate AgentMsg here.
 *
 * Under v2 the candidate list is backed by GET
 * /api/v2/debrief/roles/{id}/candidates (with eligibility tiers). The fetched
 * candidates are also stashed in session selections (`candidatePool`) so the
 * flow + analyzing animation can read names/avatars without the fixture.
 */
export function CandidatePickStage({ id }: CandidatePickStageProps) {
  const session = useSessionStore((s) => s.sessions.debrief);
  const updateSelections = useSessionStore((s) => s.updateSelections);
  const [candidates, setCandidates] = useState<CandidateFixture[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const roleId = (session?.selections.roleId as string | undefined) ?? '';

  useEffect(() => {
    if (!isV2ApiEnabled() || !roleId) return;
    let active = true;
    listCandidates(roleId)
      .then((items) => {
        if (!active) return;
        const mapped = items.map(candidateItemToFixture);
        setCandidates(mapped);
        // Stash the pool so the flow/analyzing stage can resolve display data.
        updateSelections('debrief', { candidatePool: mapped });
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : 'Failed to load candidates.');
      });
    return () => {
      active = false;
    };
  }, [roleId, updateSelections]);

  if (!session) return null;
  const roleTitle = (session.selections.roleTitle as string | undefined) ?? '';
  const selected = (session.selections.selectedCandidates as string[] | undefined) ?? [];

  return (
    <div id={id} className="pt-4">
      {error ? (
        <div id={`${id}-error`} className="text-[13px] text-text-muted">
          {error}
        </div>
      ) : (
        <CandidatePicker
          id={`${id}-picker`}
          reqId={roleId}
          roleTitle={roleTitle}
          selected={selected}
          {...(candidates ? { candidates } : {})}
          onToggle={toggleCandidate}
          onConfirm={() => {
            void confirmCandidatePick();
          }}
          onCancel={cancelCandidatePick}
        />
      )}
    </div>
  );
}
