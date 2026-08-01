'use client';

import { useRouter } from 'next/navigation';
import { BrainCanvasArtifact } from '@/components/artifacts/brain-canvas';
import { CortexAnalysisArtifact } from '@/components/artifacts/cortex-analysis';
import { CortexInsightArtifact } from '@/components/artifacts/cortex-insight';
import { DebriefPacketArtifact } from '@/components/artifacts/debrief-packet';
import { FeedbackPacketArtifact } from '@/components/artifacts/packet';
import { RequisitionArtifact } from '@/components/artifacts/requisition';
import type { SourcingResultsPillKey } from '@/components/artifacts/sourcing-results';
import { SourcingResultsArtifact } from '@/components/artifacts/sourcing-results';
import { SourcingStrategyArtifact } from '@/components/artifacts/sourcing-strategy';
import {
  clearFocus,
  draftSilverMedalistNote,
  draftSilverMedalistsAll,
  explainStory,
  filterByType,
  focusNode,
  muteStory,
  searchGraph,
  setRange,
} from '@/components/sub-agents/brain/flow';
import type { SchedulerQueueState } from '@/components/sub-agents/debrief/flow';
import { SchedulerQueue } from '@/components/sub-agents/debrief/scheduler-queue';
import {
  addStrategyCandidatesToPipeline,
  cancelSourcingRun,
  downloadStrategyJson,
  removeFilterPill,
  setPage,
  shareStrategyCopyLink,
  submitSourcingAction,
  switchStrategyTab,
  toggleCandidateSelection,
  toggleStrategyCandidate,
} from '@/components/sub-agents/sourcing/flow';
import type { Artifact } from '@/types';
import { asTypedArtifact } from '@/types';

interface ArtifactRendererProps {
  id: string;
  artifact: Artifact;
  selections: Record<string, unknown>;
}

export function ArtifactRenderer({ id, artifact, selections }: ArtifactRendererProps) {
  const router = useRouter();

  // Narrow the loosely-stored artifact to its discriminated union member. Each
  // `case` below now narrows `typed.data` to that member's data shape with no
  // per-case `as` cast, and the exhaustive `default` keeps this dispatch in
  // sync with `ArtifactType` at compile time (a new type with no case here is
  // a build error).
  const typed = asTypedArtifact(artifact);

  switch (typed.type) {
    case 'requisition':
      return <RequisitionArtifact id={id} artifactId={typed.id} />;

    case 'comparative': {
      const roleId = (selections.roleId as string | undefined) ?? '';
      const candidateIds = (selections.selectedCandidates as string[] | undefined) ?? [];
      // The REAL packet (v2) rides on the artifact's own data; the mock path
      // leaves it undefined and the artifact synthesizes from the ids above.
      const realPacket = typed.data.packet;
      return (
        <DebriefPacketArtifact
          id={id}
          artifactId={typed.id}
          reqId={roleId}
          candidateIds={candidateIds}
          {...(realPacket ? { packet: realPacket } : {})}
        />
      );
    }

    case 'candidate_packet': {
      // The debrief scheduling queue: the embedded PacketDrawer for each
      // queued candidate in turn. The queue lives on the session selections so
      // the Next/Done control and the chat flow share one source of truth.
      const queue = selections.schedulerQueue as SchedulerQueueState | null | undefined;
      if (!queue) {
        return (
          <p id={id} className="p-6 text-[13px] text-text-muted">
            Scheduling finished — reopen the debrief packet from its card in the chat.
          </p>
        );
      }
      return <SchedulerQueue id={id} roleId={typed.data.roleId ?? ''} queue={queue} />;
    }

    case 'sourcing-results':
      return (
        <SourcingResultsArtifact
          id={id}
          artifactId={typed.id}
          onRemoveFilter={(pill: SourcingResultsPillKey) => removeFilterPill(pill)}
          onToggleCandidate={(candidateId) => toggleCandidateSelection(candidateId)}
          onPageChange={(page) => setPage(page)}
          onAddSelectedToPipeline={() => void submitSourcingAction('add_to_pipeline')}
          onSendOutreach={() => void submitSourcingAction('send_outreach')}
          onExport={() => void submitSourcingAction('export')}
        />
      );

    case 'packet':
      return <FeedbackPacketArtifact id={id} artifactId={typed.id} />;

    case 'brain-canvas':
      return (
        <BrainCanvasArtifact
          id={id}
          artifactId={typed.id}
          onStoryExplain={(storyId) => explainStory(storyId)}
          onStoryMute={(storyId) => muteStory(storyId)}
          onNodeFocus={(nodeId) => focusNode(nodeId)}
          onRangeChange={(rangeId) => setRange(rangeId)}
          onClearFocus={() => clearFocus()}
          onSearch={(q) => searchGraph(q)}
          onFilterType={(type) => filterByType(type)}
        />
      );

    case 'cortex-insight':
      return <CortexInsightArtifact id={id} artifactId={typed.id} />;

    case 'cortex-analysis':
      return (
        <CortexAnalysisArtifact
          id={id}
          artifactId={typed.id}
          onDraftNote={(candidateId) => draftSilverMedalistNote(candidateId)}
          onDraftAll={() => draftSilverMedalistsAll()}
        />
      );

    case 'sourcing-strategy': {
      const strategySelections = selections as { roleId?: string | null };
      return (
        <SourcingStrategyArtifact
          id={id}
          artifactId={typed.id}
          onToggleCandidate={(candId) => toggleStrategyCandidate(candId)}
          onAddSelectedToPipeline={() => void addStrategyCandidatesToPipeline()}
          onShareStrategy={() => {
            shareStrategyCopyLink();
          }}
          onDownloadStrategy={() => downloadStrategyJson()}
          onSwitchTab={(tab) => switchStrategyTab(tab)}
          onBackToRole={() => {
            const rid = strategySelections.roleId ?? null;
            if (rid) {
              cancelSourcingRun();
              router.push(`/view/roles/${rid}`);
            }
          }}
        />
      );
    }

    default: {
      // Exhaustiveness guard: if a new `ArtifactType` is added without a case
      // above, `typed` is no longer `never` here and this fails to compile —
      // keeping the dispatch in sync with the union. At runtime this branch is
      // only reachable via a malformed/stale artifact, so we still render a
      // safe fallback instead of crashing the column.
      const _exhaustive: never = typed;
      const unknownType = (_exhaustive as { type: string }).type;
      return (
        <div id={`${id}-unknown`} className="text-text-muted">
          Renderer for {unknownType} coming soon.
        </div>
      );
    }
  }
}
