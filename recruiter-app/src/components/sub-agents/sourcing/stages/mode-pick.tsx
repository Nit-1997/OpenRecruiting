'use client';

import { useEffect, useRef } from 'react';
import { useSessionStore } from '@/stores';
import { runSourcingStage } from '../flow';

interface ModePickStageProps {
  id: string;
}

/**
 * Mode pick is driven by the scripted stream — prose, sub, and the two
 * [existing / fresh] CTA chips all land on the streamed message itself, so
 * TranscriptTail renders the full greeting as a single display bubble.
 * This component only kicks the stream on mount.
 */
export function ModePickStage({ id }: ModePickStageProps) {
  const session = useSessionStore((s) => s.sessions.sourcing);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    if (session && session.messages.length === 0 && session.stage === 'mode_pick') {
      started.current = true;
      void runSourcingStage('mode_pick');
    }
  }, [session]);

  return <div id={id} aria-hidden className="sr-only" />;
}
