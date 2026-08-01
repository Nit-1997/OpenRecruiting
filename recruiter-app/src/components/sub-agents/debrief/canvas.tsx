'use client';

import { useSearchParams } from 'next/navigation';
import { useEffect, useRef } from 'react';
import { ThinkingPill, TranscriptTail } from '@/components/shell/primitives';
import { REQS, type RoleFixture } from '@/fixtures/roles';
import { useShellSync } from '@/hooks/use-shell-sync';
import { isV2ApiEnabled } from '@/lib/env';
import { cancelRun } from '@/lib/sub-agent-runner';
import { useComposerStore, useSessionStore, useTypingStore } from '@/stores';
import { initDebriefFromRole, submitDebriefMessage } from './flow';
import { AnalyzingStage } from './stages/analyzing';
import { CandidatePickStage } from './stages/candidate-pick';
import { FailedStage } from './stages/failed';
import { ResultStage } from './stages/result';
import { RolePickStage } from './stages/role-pick';

interface DebriefCanvasProps {
  id: string;
}

export function DebriefCanvas({ id }: DebriefCanvasProps) {
  useShellSync();
  const session = useSessionStore((s) => s.sessions.debrief);
  const startSession = useSessionStore((s) => s.startSession);
  const setAgenticScope = useComposerStore((s) => s.setAgenticScope);
  const searchParams = useSearchParams();
  const roleQuery = searchParams?.get('role') ?? null;
  const titleQuery = searchParams?.get('title') ?? null;
  // Tracks the roleQuery we last initialized for. Persists across strict-mode
  // replays so we don't double-init (which would duplicate "Got it —…" and
  // trigger an unwanted role_pick greeting).
  const initializedForRole = useRef<string | null>(null);

  useEffect(() => {
    setAgenticScope('debrief');
  }, [setAgenticScope]);

  useEffect(() => {
    if (roleQuery) {
      if (initializedForRole.current === roleQuery) return;
      // Under v2 the role id is a real production requisition with no fixture —
      // resolve the display title from the `title` query param (the role tab's
      // "Generate in agent" link supplies it). A missing title degrades to a
      // neutral label rather than silently bailing. Mock mode keeps the
      // fixture lookup so the demo roles still render their rich metadata.
      let role: RoleFixture | undefined;
      if (isV2ApiEnabled()) {
        role = {
          id: roleQuery,
          title: titleQuery ?? 'this role',
          loc: '',
          pipeline: '',
          status: 'live',
          dept: '',
          owner: '',
          created_at: '',
          ready_to_debrief: true,
          must_have: [],
          nice_to_have: [],
        };
      } else {
        role = REQS.find((r) => r.id === roleQuery);
      }
      if (!role) return;
      initializedForRole.current = roleQuery;
      void initDebriefFromRole(role);
      return;
    }

    // Fresh entry: only start a session if none exists. Never stomp an
    // existing session (e.g. one the user was mid-flow on).
    if (!session) {
      startSession('debrief', 'role_pick');
    }
  }, [session, startSession, roleQuery, titleQuery]);

  // Cancel any in-flight debrief stage stream on unmount so its async chain
  // stops mutating the torn-down session after navigating away (mirrors
  // sourcing's unmount-cancel).
  useEffect(() => {
    return () => {
      cancelRun('debrief');
    };
  }, []);

  const stage = session?.stage ?? 'role_pick';
  const thinking = useTypingStore((s) => s.typing.debrief ?? false);
  // Show the thinking indicator whenever the agent is composing OR the
  // session hasn't been initialized yet (tiny gap between canvas mount and
  // the session-creation effect firing). Prevents the stage UX flashing in
  // before the chat bubble that introduces it.
  const showThinking = thinking || !session;

  const renderStage = () => {
    switch (stage) {
      case 'role_pick':
        return <RolePickStage id={`${id}-stage-role-pick`} />;
      case 'candidate_pick':
        return <CandidatePickStage id={`${id}-stage-candidate-pick`} />;
      case 'analyzing':
        return <AnalyzingStage id={`${id}-stage-analyzing`} />;
      case 'result':
        return <ResultStage id={`${id}-stage-result`} />;
      case 'failed':
        return <FailedStage id={`${id}-stage-failed`} />;
      default:
        return <RolePickStage id={`${id}-stage-role-pick`} />;
    }
  };

  return (
    <div id={id}>
      <TranscriptTail
        id={`${id}-transcript`}
        tabId="debrief"
        onChip={(chip) => {
          void submitDebriefMessage(chip.label);
        }}
      />
      {showThinking ? (
        <ThinkingPill id={`${id}-thinking`} label="OpenRecruiting is pulling interview signal…" />
      ) : (
        renderStage()
      )}
    </div>
  );
}
