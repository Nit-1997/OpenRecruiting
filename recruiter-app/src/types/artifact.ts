import type { BrainCanvasArtifactData } from '@/components/artifacts/brain-canvas';
import type { CortexAnalysisData } from '@/components/artifacts/cortex-analysis';
import type { CortexInsightArtifactData } from '@/components/artifacts/cortex-insight';
import type { FeedbackPacketArtifactData } from '@/components/artifacts/packet';
import type { SourcingResultsArtifactData } from '@/components/artifacts/sourcing-results';
import type { SourcingStrategyArtifactData } from '@/components/artifacts/sourcing-strategy';
import type { DebriefPacket } from '@/fixtures/debrief-packets';

// Every artifact type the renderer knows how to draw. Each one is constructed
// by a sub-agent flow (or the scripted mock-stream runner) and has a matching
// `case` in `artifact-renderer.tsx`. Adding a member here without a renderer
// case — or a renderer case without a member — is now a compile error via
// `ArtifactDataMap` below, which keeps the dispatch in sync with the union.
export type ArtifactType =
  | 'requisition'
  | 'comparative'
  | 'packet'
  | 'candidate_packet'
  | 'sourcing-results'
  | 'sourcing-strategy'
  | 'cortex-insight'
  | 'cortex-analysis'
  | 'brain-canvas';

export type ArtifactExpanded = 'collapsed' | 'default' | 'expanded';

export type ArtifactStatus = 'draft' | 'active' | 'paused' | 'archived';

// The `comparative` artifact carries the pointers the debrief flow seeds
// (`src/components/sub-agents/debrief/flow.ts`). Under v2 it also carries the
// REAL fetched `DebriefPacket` (`packet`); the renderer draws that directly.
// On the mock path `packet` is absent and the artifact synthesizes from ids.
export interface ComparativeArtifactData {
  roleId: string;
  roleTitle: string;
  candidateIds: string[];
  packet?: DebriefPacket;
}

// The `candidate_packet` artifact hosts the debrief scheduling queue: the role
// section's real PacketDrawer (embedded variant) rendered INSIDE the workspace
// column, one queued candidate at a time. The queue itself lives on the debrief
// session's `selections.schedulerQueue`; the artifact only pins the role.
export interface CandidatePacketArtifactData {
  roleId: string;
}

// The live `requisition` artifact reads its state from `useRequisitionStore`,
// so its `data` slot is empty at render. This shape documents the historical
// intake contract and is intentionally not read by `RequisitionArtifact`.
export interface RequisitionArtifactData {
  sub?: string;
  published?: boolean;
}

// Maps every renderable artifact type to its fully-patched `data` shape. This
// is the single source of truth that ties `type` to `data`: the discriminated
// `TypedArtifact` union and the `ArtifactDataFor<T>` helper are both derived
// from it, so a mis-tagged artifact is a compile error rather than a silent
// runtime crash.
export interface ArtifactDataMap {
  requisition: RequisitionArtifactData;
  comparative: ComparativeArtifactData;
  packet: FeedbackPacketArtifactData;
  candidate_packet: CandidatePacketArtifactData;
  'sourcing-results': SourcingResultsArtifactData;
  'sourcing-strategy': SourcingStrategyArtifactData;
  'cortex-insight': CortexInsightArtifactData;
  'cortex-analysis': CortexAnalysisData;
  'brain-canvas': BrainCanvasArtifactData;
}

export type ArtifactDataFor<T extends ArtifactType> = ArtifactDataMap[T];

// Discriminated union: narrowing on `type` narrows `data` with no `as` cast.
export type TypedArtifact = {
  [K in ArtifactType]: {
    id: string;
    type: K;
    title: string;
    data: ArtifactDataMap[K];
    isBuilding: boolean;
    expanded: ArtifactExpanded;
    status?: ArtifactStatus;
  };
}[ArtifactType];

// LOOSE stored shape. The zustand artifact-store keys heterogeneous artifacts
// by id and patches `data` incrementally, so it stores this looser type with
// `data: unknown`. Consumers narrow to `TypedArtifact` via `asTypedArtifact`
// (renderer) or the `useTypedArtifact` store hook (components).
export interface Artifact<T = unknown> {
  id: string;
  type: ArtifactType;
  title: string;
  data: T;
  isBuilding: boolean;
  expanded: ArtifactExpanded;
  status?: ArtifactStatus;
}

// Narrows a loosely-stored Artifact to its discriminated union member. The cast
// is the ONE place blind `data as X` is centralised: data is patched
// incrementally so the runtime value may be partial, exactly as the per-type
// components already guard for. Returns the artifact typed by its discriminant.
export function asTypedArtifact(artifact: Artifact): TypedArtifact {
  return artifact as unknown as TypedArtifact;
}
