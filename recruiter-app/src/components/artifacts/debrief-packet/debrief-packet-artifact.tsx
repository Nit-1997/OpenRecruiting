'use client';

import { useMemo } from 'react';
import { DebriefPacketBody, DebriefPacketToolbar } from '@/components/debrief-packet/packet-view';
import { PrintPortal } from '@/components/debrief-packet/print-portal';
import { SaveDebriefButton } from '@/components/debrief-packet/save-debrief-button';
import { type DebriefPacket, getDebriefPackets } from '@/fixtures/debrief-packets';
import { synthesizePacket } from './synthesize-packet';

interface DebriefPacketArtifactProps {
  id: string;
  artifactId: string;
  reqId: string;
  candidateIds: string[];
  /** The REAL fetched packet (v2). When present it is rendered directly; the
   *  fixture/synthesize fallback is for the mock path only. */
  packet?: DebriefPacket;
}

export function DebriefPacketArtifact({
  id,
  reqId,
  candidateIds,
  packet: realPacket,
}: DebriefPacketArtifactProps) {
  const packet = useMemo(() => {
    // v2: render the real fetched packet verbatim (DebriefPacketResponse is
    // field-identical to DebriefPacket — zero translation).
    if (realPacket) return realPacket;
    const existing = getDebriefPackets(reqId);
    const matching = existing.find((p) =>
      candidateIds.every((cid) => p.candidates.some((c) => c.candidate_id === cid)),
    );
    if (matching) return matching;
    return synthesizePacket(reqId, candidateIds);
  }, [reqId, candidateIds, realPacket]);

  if (!packet) {
    return (
      <div id={id} className="p-6 text-[13px] text-text-muted">
        Pick 2 or more candidates to compare.
      </div>
    );
  }

  // Save lives in the toolbar (next to Download) for a REAL, still-uncommitted
  // (draft) packet only — a mock or already-committed packet has nothing to save.
  const canSave = Boolean(realPacket) && packet.status === 'draft';

  return (
    <section id={id} aria-label="Comparative debrief packet" className="flex min-w-0 flex-col">
      <DebriefPacketToolbar
        id={id}
        packet={packet}
        trailing={
          canSave ? (
            <SaveDebriefButton id={id} packetId={packet.id} roleId={packet.requisition_id} />
          ) : undefined
        }
      />
      <div id={`${id}-scroll`} className="bg-surface/30 px-4 py-5 sm:px-6 sm:py-6">
        <DebriefPacketBody id={`${id}-body`} packet={packet} />
      </div>

      {/* Mounted under <body> as `.print-portal`; hidden on screen, revealed in
          print. The toolbar Download fires window.print() and this captures the
          live packet in place — no separate print route. */}
      <PrintPortal>
        <DebriefPacketBody id={`${id}-print-body`} packet={packet} />
      </PrintPortal>
    </section>
  );
}
