'use client';

import { useEffect, useRef } from 'react';
import type { CandidateFixture } from '@/fixtures/candidates';
import { useSessionStore } from '@/stores';
import { DebriefAnalyzing } from '../analyzing-animation';
import { completeAnalyzing, resolveCandidateMeta } from '../flow';

interface AnalyzingStageProps {
  id: string;
}

export function AnalyzingStage({ id }: AnalyzingStageProps) {
  const session = useSessionStore((s) => s.sessions.debrief);
  const completed = useRef(false);

  useEffect(() => {
    return () => {
      completed.current = false;
    };
  }, []);

  if (!session) return null;
  const roleId = (session.selections.roleId as string | undefined) ?? '';
  const roleTitle = (session.selections.roleTitle as string | undefined) ?? 'this role';
  const selected = (session.selections.selectedCandidates as string[] | undefined) ?? [];
  // Single-source the display-metadata resolution with the flow: under v2 prefer
  // the real candidates the picker stashed in `candidatePool`; fall back to the
  // static fixture only when absent (the mock path).
  const pool = session.selections.candidatePool as CandidateFixture[] | undefined;
  const candidates = resolveCandidateMeta(roleId, selected, pool);
  const names = candidates.map((c) => c.name.split(' ')[0] ?? c.name);
  const avatars = candidates.map((c) => ({ initials: c.avatar, color: c.color }));

  const handleDone = () => {
    if (completed.current) return;
    completed.current = true;
    void completeAnalyzing();
  };

  return (
    <DebriefAnalyzing
      id={id}
      roleTitle={roleTitle}
      candidateNames={names}
      candidateAvatars={avatars}
      onDone={handleDone}
    />
  );
}
