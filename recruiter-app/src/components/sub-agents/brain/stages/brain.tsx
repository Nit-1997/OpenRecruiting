'use client';

import { useEffect, useRef } from 'react';
import { useArtifactStore, useSessionStore } from '@/stores';
import { rehydrateBrain, runBrainStage, submitBrainInput } from '../flow';
import { BRAIN_ARTIFACT_ID } from '../mock-stream';

interface BrainStageProps {
  id: string;
}

const QUICK_PROMPTS = [
  { label: 'Explain scoring drift', value: 'explain scoring drift' },
  { label: 'Drill into Ben', value: 'drill into Ben' },
  { label: "What's causing pipeline risk?", value: "what's causing pipeline risk" },
  { label: 'Compare Q1 to Q2', value: 'compare Q1 to Q2' },
];

/**
 * Brain stage UX — kicks off the opening stream on first mount, and renders
 * only the "assembling graph…" indicator + quick-prompt chips. Message
 * history is rendered by the canvas's TranscriptTail, so we avoid
 * duplicating bubbles here.
 */
export function BrainStage({ id }: BrainStageProps) {
  const session = useSessionStore((s) => s.sessions.brain);
  const artifact = useArtifactStore((s) => s.artifacts[BRAIN_ARTIFACT_ID]);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    if (!session) return;
    if (session.stage !== 'brain') return;
    if (session.messages.length > 0) {
      started.current = true;
      if (!useArtifactStore.getState().artifacts[BRAIN_ARTIFACT_ID]) {
        void rehydrateBrain();
      }
      return;
    }
    started.current = true;
    void runBrainStage();
  }, [session]);

  if (!session) return null;

  return (
    <div id={id} className="flex min-w-0 flex-col gap-3 pt-2">
      {artifact?.isBuilding && (
        <div
          id={`${id}-assembling`}
          className="ml-11 inline-flex items-center gap-2 font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]"
        >
          <span aria-hidden className="h-1.5 w-1.5 animate-pulse rounded-full bg-cortex-500" />
          Assembling the graph...
        </div>
      )}
      <div id={`${id}-prompts`} className="mt-2 ml-11 flex max-w-[620px] flex-wrap gap-2">
        {QUICK_PROMPTS.map((p, idx) => (
          <button
            key={p.value}
            id={`${id}-prompt-${idx}`}
            type="button"
            onClick={() => {
              void submitBrainInput(p.value);
            }}
            className="inline-flex items-center rounded-full border border-border/70 bg-white/70 px-3 py-1.5 font-medium font-sans text-[12.5px] text-text-primary shadow-[0_1px_2px_rgba(0,0,0,0.03)] backdrop-blur-sm transition-colors hover:border-text-primary hover:bg-white/85"
          >
            {p.label}
          </button>
        ))}
      </div>
    </div>
  );
}
