'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useRef } from 'react';
import { ThinkingPill, TranscriptTail } from '@/components/shell/primitives';
import { useRequisition } from '@/hooks/use-services';
import { useShellSync } from '@/hooks/use-shell-sync';
import { makeMessage } from '@/lib/sub-agent-runner';
import { useComposerStore, useSessionStore, useTypingStore } from '@/stores';
import {
  addStrategyCandidatesToPipeline,
  cancelSourcingRun,
  handlePreferenceChip,
  pickMode,
  startSourcingForRole,
} from './flow';
import { ModePickStage } from './stages/mode-pick';
import { QueryBuildStage } from './stages/query-build';
import { ResultsStage } from './stages/results';
import { RolePickStage } from './stages/role-pick';

interface SourcingCanvasProps {
  id: string;
}

export function SourcingCanvas({ id }: SourcingCanvasProps) {
  useShellSync();
  const router = useRouter();
  const session = useSessionStore((s) => s.sessions.sourcing);
  const startSession = useSessionStore((s) => s.startSession);
  const setAgenticScope = useComposerStore((s) => s.setAgenticScope);
  const searchParams = useSearchParams();
  const roleQueryId = searchParams?.get('role') ?? null;
  const intent = searchParams?.get('intent') ?? null;
  const isDeepLinked = intent === 'source' && !!roleQueryId;
  const { data: role } = useRequisition(roleQueryId ?? '');
  const deepLinkTriggered = useRef<string | null>(null);

  useEffect(() => {
    setAgenticScope('sourcing');
  }, [setAgenticScope]);

  useEffect(() => {
    if (isDeepLinked) {
      // Deep-link entry: start the sourcing session directly at preferences_chat
      // so we never render the mode-pick "existing vs fresh" greeting.
      if (!session) {
        startSession('sourcing', 'preferences_chat');
      } else if (session.stage === 'mode_pick' && session.messages.length === 0) {
        useSessionStore.getState().setStage('sourcing', 'preferences_chat');
      }
      return;
    }
    if (!session) {
      startSession('sourcing', 'mode_pick');
    }
  }, [session, startSession, isDeepLinked]);

  useEffect(() => {
    if (!isDeepLinked) return;
    if (!roleQueryId || !role) return;
    if (deepLinkTriggered.current === roleQueryId) return;
    deepLinkTriggered.current = roleQueryId;
    void startSourcingForRole(roleQueryId, role.role_title);
  }, [isDeepLinked, roleQueryId, role]);

  // Cancel any running sourcing animation on unmount so async patches don't
  // race Next's RSC fetch when navigating away ("See the role").
  useEffect(() => {
    return () => {
      cancelSourcingRun();
    };
  }, []);

  const stage = session?.stage ?? 'mode_pick';
  const thinking = useTypingStore((s) => s.typing.sourcing ?? false);
  const showThinking = thinking || !session;

  const renderStage = () => {
    // When deep-linked from a role, don't render mode_pick — preferences_chat
    // takes over the moment the role loads.
    if (isDeepLinked && stage === 'mode_pick') {
      return null;
    }
    switch (stage) {
      case 'mode_pick':
        return <ModePickStage id={`${id}-stage-mode-pick`} />;
      case 'role_pick':
        return <RolePickStage id={`${id}-stage-role-pick`} />;
      case 'query_build':
        return <QueryBuildStage id={`${id}-stage-query-build`} />;
      case 'results':
        return <ResultsStage id={`${id}-stage-results`} />;
      case 'preferences_chat':
      case 'strategy_publish':
      case 'channel_stream':
      case 'candidate_stream':
      case 'offer_add':
        // Right-panel artifact carries the refined-flow UX. Chat-side stage
        // surface is intentionally empty — transcript + chips drive the action.
        return null;
      default:
        return <ModePickStage id={`${id}-stage-mode-pick`} />;
    }
  };

  const handleChipFromTranscript = (chip: { value: string }) => {
    if (chip.value === 'existing' || chip.value === 'fresh') {
      void pickMode(chip.value);
      return;
    }
    if (chip.value === 'start_sourcing_defaults' || chip.value.startsWith('pref_')) {
      void handlePreferenceChip(chip.value);
      return;
    }
    if (chip.value === 'add_strategy_candidates') {
      useSessionStore
        .getState()
        .appendMessage('sourcing', makeMessage('user', 'Add the top 5 to my pipeline.'));
      void addStrategyCandidatesToPipeline();
      return;
    }
    if (chip.value === 'see_all_strategy_matches') {
      useSessionStore
        .getState()
        .appendMessage(
          'sourcing',
          makeMessage(
            'agent',
            '45 matches available — opening the full results view in a future release.',
          ),
        );
      return;
    }
    if (chip.value === 'back_to_role') {
      const roleId =
        (useSessionStore.getState().sessions.sourcing?.selections.roleId as string | undefined) ??
        roleQueryId;
      if (roleId) {
        cancelSourcingRun();
        router.push(`/view/roles/${roleId}`);
      }
      return;
    }
  };

  return (
    <div id={id} className="flex min-h-full flex-col">
      <TranscriptTail
        id={`${id}-transcript`}
        tabId="sourcing"
        onChip={handleChipFromTranscript}
        skipDisplayFirst={isDeepLinked}
      />
      {showThinking ? (
        <ThinkingPill id={`${id}-thinking`} label="OpenRecruiting is searching the candidate pool…" />
      ) : (
        renderStage()
      )}
    </div>
  );
}
