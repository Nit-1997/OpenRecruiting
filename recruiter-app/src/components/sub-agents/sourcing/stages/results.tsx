'use client';

import { useEffect, useRef } from 'react';
import { AgentMsg, UserMsg } from '@/components/sub-agents/intake/primitives';
import { cn } from '@/lib/utils';
import { useArtifactStore, useSessionStore } from '@/stores';
import { rehydrateResults, type SourcingSelections, submitSourcingAction } from '../flow';
import { SOURCING_ARTIFACT_ID, type SourcingActionIntent } from '../mock-stream';

interface ResultsStageProps {
  id: string;
}

interface ChipDef {
  label: string;
  value: string;
  intent: SourcingActionIntent;
  primary?: boolean;
}

export function ResultsStage({ id }: ResultsStageProps) {
  const session = useSessionStore((s) => s.sessions.sourcing);
  const artifact = useArtifactStore((s) => s.artifacts[SOURCING_ARTIFACT_ID]);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const rehydrated = useRef(false);

  const selections = (session?.selections as SourcingSelections | undefined) ?? null;

  useEffect(() => {
    if (rehydrated.current) return;
    if (!selections?.criteria) return;
    const hasArtifact = useArtifactStore.getState().artifacts[SOURCING_ARTIFACT_ID];
    if (hasArtifact) {
      rehydrated.current = true;
      return;
    }
    rehydrated.current = true;
    void rehydrateResults();
  }, [selections?.criteria]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll on every message count change
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [session?.messages.length]);

  if (!session) return null;

  const chips: ChipDef[] = [
    {
      label: 'Refine filters',
      value: 'refine',
      intent: 'refine_filters',
      primary: true,
    },
    {
      label: 'Add selected to pipeline',
      value: 'add',
      intent: 'add_to_pipeline',
    },
    { label: 'Send outreach', value: 'outreach', intent: 'send_outreach' },
    { label: 'Export', value: 'export', intent: 'export' },
  ];

  return (
    <div
      id={`${id}-chat`}
      ref={scrollRef}
      role="log"
      aria-live="polite"
      aria-atomic="false"
      aria-label="Sourcing agent chat transcript"
      className="flex min-w-0 flex-col gap-3 pt-2"
    >
      {session.messages
        .filter((m) => m.source !== 'chat')
        .map((m) =>
          m.role === 'agent' ? (
            <AgentMsg key={m.id} id={`${id}-msg-${m.id}`} variant="small">
              {m.text}
            </AgentMsg>
          ) : (
            <UserMsg key={m.id} id={`${id}-msg-${m.id}`} text={m.text} mode={m.mode ?? 'text'} />
          ),
        )}
      {artifact?.isBuilding && (
        <div
          id={`${id}-thinking`}
          className="ml-11 inline-flex items-center gap-2 font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]"
        >
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-cortex-500" aria-hidden />
          Streaming matches...
        </div>
      )}

      <div id={`${id}-chips`} className="mt-3 ml-11 flex max-w-[620px] flex-wrap gap-2">
        {chips.map((chip) => (
          <button
            key={chip.value}
            id={`${id}-chip-${chip.value}`}
            type="button"
            onClick={() => {
              void submitSourcingAction(chip.intent);
            }}
            className={cn(
              'inline-flex items-center rounded-full border px-3 py-1.5 font-medium font-sans text-[12.5px] transition-colors',
              chip.primary
                ? 'border-text-primary bg-text-primary text-white hover:bg-[#222]'
                : 'border-border/70 bg-white/70 text-text-primary shadow-[0_1px_2px_rgba(0,0,0,0.03)] backdrop-blur-sm hover:border-text-primary hover:bg-white/85',
            )}
          >
            {chip.label}
          </button>
        ))}
      </div>
    </div>
  );
}
