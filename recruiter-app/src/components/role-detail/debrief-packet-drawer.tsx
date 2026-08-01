'use client';

import { RefreshCw, X } from 'lucide-react';
import { useEffect } from 'react';
import { DebriefPacketBody, DebriefPacketToolbar } from '@/components/debrief-packet/packet-view';
import { PrintPortal } from '@/components/debrief-packet/print-portal';
import type { DebriefPacket } from '@/fixtures/debrief-packets';

interface DebriefPacketDrawerProps {
  id: string;
  packet: DebriefPacket;
  onClose: () => void;
}

export function DebriefPacketDrawer({ id, packet, onClose }: DebriefPacketDrawerProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div id={id} className="fixed inset-0 z-40 flex justify-end bg-black/30" role="presentation">
      <button
        type="button"
        aria-label="Close debrief packet"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-transparent"
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-head-title`}
        className="relative flex h-full w-full max-w-[1120px] flex-col overflow-hidden border-border border-l bg-white shadow-[0_0_80px_rgba(0,0,0,0.22)]"
      >
        <DebriefPacketToolbar
          id={id}
          packet={packet}
          trailing={
            <button
              id={`${id}-close`}
              type="button"
              aria-label="Close debrief packet"
              onClick={onClose}
              className="ml-1 flex h-8 w-8 items-center justify-center rounded-full text-text-muted hover:bg-surface hover:text-text-primary"
            >
              <X strokeWidth={1.75} className="h-4 w-4" />
            </button>
          }
        />

        <div className="flex-1 overflow-y-auto bg-surface/30 px-4 py-5 sm:px-8 sm:py-8">
          <div className="mx-auto flex max-w-[1000px] flex-col gap-6">
            <DebriefPacketBody id={`${id}-body`} packet={packet} />
          </div>
        </div>

        {/* Mounted under <body> as `.print-portal`; hidden on screen, revealed
            in print. The toolbar Download fires window.print() and this captures
            the live packet in place — no separate print route. */}
        <PrintPortal>
          <DebriefPacketBody id={`${id}-print-body`} packet={packet} />
        </PrintPortal>

        <footer className="flex flex-wrap items-center justify-between gap-3 border-border border-t bg-white px-4 py-3 sm:px-6">
          <p className="text-[12px] text-text-muted">
            Drafted by OpenRecruiting debrief agent · open the agent to regenerate after new feedback.
          </p>
          <div className="flex items-center gap-2">
            <button
              id={`${id}-action-regenerate`}
              type="button"
              disabled
              title="Open the debrief agent to regenerate from new feedback."
              className="inline-flex items-center gap-1.5 rounded-full border border-border bg-white px-3 py-1.5 font-medium font-sans text-[12px] text-text-muted"
            >
              <RefreshCw strokeWidth={1.75} className="h-3.5 w-3.5" />
              Regenerate in agent
            </button>
          </div>
        </footer>
      </aside>
    </div>
  );
}
