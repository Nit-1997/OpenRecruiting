'use client';

import { ArrowRight, Check } from 'lucide-react';
import { PacketDrawer } from '@/components/packet-drawer/drawer';
import type { CandidateFixture } from '@/fixtures/candidates';
import { useSessionStore } from '@/stores';
import {
  advanceSchedulerQueue,
  closeScheduler,
  finishSchedulerQueue,
  type SchedulerQueueState,
} from './flow';

interface SchedulerQueueProps {
  id: string;
  roleId: string;
  queue: SchedulerQueueState;
}

/**
 * The debrief scheduling work-queue, rendered INSIDE the workspace artifact
 * column (the `candidate_packet` artifact) so its geometry matches the debrief
 * packet exactly and the chat column never reflows. It hosts the role
 * section's PacketDrawer (embedded variant) for the current candidate, plus —
 * when more than one candidate was asked for — a floating "Next: <name>" /
 * "Done" control so the recruiter walks through every candidate without
 * re-asking the agent. The control overlays the packet's bottom-right corner;
 * the drawer's own schedule modal portals above it. The drawer's X abandons
 * the queue. Height is viewport-bound (the artifact column scrolls its content
 * naturally; the drawer manages its own internal scroll).
 */
export function SchedulerQueue({ id, roleId, queue }: SchedulerQueueProps) {
  const pool = useSessionStore(
    (s) => s.sessions.debrief?.selections.candidatePool as CandidateFixture[] | undefined,
  );
  const candidateId = queue.candidateIds[queue.index];
  if (!candidateId) return null;

  const nameOf = (cid: string | undefined): string | null => {
    if (!cid) return null;
    return pool?.find((c) => c.id === cid)?.name ?? null;
  };
  const isLast = queue.index >= queue.candidateIds.length - 1;
  const nextName = isLast ? null : nameOf(queue.candidateIds[queue.index + 1]);
  const currentName = nameOf(candidateId);

  return (
    <div id={id} className="relative flex h-[calc(100dvh-190px)] min-h-[480px] min-w-0 flex-col">
      <PacketDrawer
        key={candidateId}
        id={`${id}-packet`}
        reqId={roleId}
        candidateId={candidateId}
        initialRoundId={null}
        variant="embedded"
        onClose={closeScheduler}
      />
      {queue.candidateIds.length > 1 && (
        <div
          id={`${id}-bar`}
          className="absolute right-4 bottom-4 z-10 flex items-center gap-3 rounded-full border border-border bg-white px-4 py-2.5 shadow-[0_8px_24px_rgba(0,0,0,0.18)]"
        >
          <span id={`${id}-bar-label`} className="font-sans text-[12.5px] text-text-muted">
            Scheduling {queue.index + 1} of {queue.candidateIds.length}
            {currentName ? ` — ${currentName}` : ''}
          </span>
          <button
            id={`${id}-bar-advance`}
            type="button"
            onClick={() => {
              if (isLast) finishSchedulerQueue();
              else advanceSchedulerQueue();
            }}
            className="inline-flex items-center gap-1.5 rounded-full bg-text-primary px-3.5 py-1.5 font-medium font-sans text-[12.5px] text-white transition-colors hover:bg-[#222]"
          >
            {isLast ? (
              <>
                <Check strokeWidth={2} className="h-3.5 w-3.5" aria-hidden />
                <span>Done</span>
              </>
            ) : (
              <>
                <span>Next{nextName ? `: ${nextName}` : ' candidate'}</span>
                <ArrowRight strokeWidth={2} className="h-3.5 w-3.5" aria-hidden />
              </>
            )}
          </button>
        </div>
      )}
    </div>
  );
}
