'use client';

import { ChevronUp } from 'lucide-react';
import { HOME_HISTORY } from '@/fixtures/home-history';
import { SUB_AGENT_HISTORY } from '@/fixtures/sub-agent-history';
import { isV2ApiEnabled } from '@/lib/env';
import { useSessionStore } from '@/stores';
import type { ChatTabId, SubAgentId } from '@/types';

interface LoadPreviousPillProps {
  id: string;
  agentId: ChatTabId;
}

function seedsFor(agentId: ChatTabId) {
  if (agentId === 'home') return HOME_HISTORY;
  return SUB_AGENT_HISTORY[agentId as SubAgentId] ?? [];
}

export function LoadPreviousPill({ id, agentId }: LoadPreviousPillProps) {
  const session = useSessionStore((s) => s.sessions[agentId]);
  const archivedCount = useSessionStore((s) => s.archived[agentId]?.length ?? 0);
  const loadEarlier = useSessionStore((s) => s.loadEarlier);

  // Real archived sessions (persisted across reloads) always offer restore.
  // The fixture-seed fallback exists for the mock/demo path only — never
  // fabricate history when the v2 API serves real data.
  const seeds = isV2ApiEnabled() ? [] : seedsFor(agentId);
  const cursor = Number(session?.selections.earlierCursor ?? 0);
  const hasSeeds = seeds.length > 0 && cursor < seeds.length;
  if (archivedCount === 0 && !hasSeeds) return null;

  return (
    <div className="flex justify-center pb-1">
      <button
        id={id}
        type="button"
        onClick={() => loadEarlier(agentId)}
        className="inline-flex items-center gap-1.5 rounded-full border border-border bg-transparent px-4 py-1.5 font-mono text-[11px] text-text-muted uppercase tracking-[0.22em] transition-colors hover:border-text-muted hover:text-text-secondary"
      >
        <ChevronUp strokeWidth={1.75} className="h-3 w-3" />
        <span>Show earlier</span>
      </button>
    </div>
  );
}
