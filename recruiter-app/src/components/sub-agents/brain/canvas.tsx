'use client';

import { useEffect } from 'react';
import { ThinkingPill, TranscriptTail } from '@/components/shell/primitives';
import { useShellSync } from '@/hooks/use-shell-sync';
import { cancelRun } from '@/lib/sub-agent-runner';
import { useComposerStore, useSessionStore, useTypingStore } from '@/stores';
import { submitBrainInput } from './flow';
import { BrainStage } from './stages/brain';

interface BrainCanvasProps {
  id: string;
}

export function BrainCanvas({ id }: BrainCanvasProps) {
  useShellSync();
  const session = useSessionStore((s) => s.sessions.brain);
  const startSession = useSessionStore((s) => s.startSession);
  const setAgenticScope = useComposerStore((s) => s.setAgenticScope);

  useEffect(() => {
    setAgenticScope('brain');
  }, [setAgenticScope]);

  useEffect(() => {
    if (!session) {
      startSession('brain', 'brain');
    }
  }, [session, startSession]);

  // Cancel any in-flight Cortex-insight animation on unmount so its async
  // delay chain stops patching the artifact/session store after navigating
  // away (mirrors sourcing's unmount-cancel).
  useEffect(() => {
    return () => {
      cancelRun('brain');
    };
  }, []);

  const stage = session?.stage ?? 'brain';
  const thinking = useTypingStore((s) => s.typing.brain ?? false);
  const showThinking = thinking || !session;

  return (
    <div id={id} className="flex min-h-full flex-col">
      <TranscriptTail
        id={`${id}-transcript`}
        tabId="brain"
        onChip={(chip) => {
          void submitBrainInput(chip.value);
        }}
      />
      {showThinking ? (
        <ThinkingPill id={`${id}-thinking`} label="OpenRecruiting is synthesizing pipeline signal…" />
      ) : stage === 'brain' ? (
        <BrainStage id={`${id}-stage-brain`} />
      ) : null}
    </div>
  );
}
