import type { FC } from 'react';
import type { SubAgentMockStream } from '@/lib/sub-agent-runner';
import { useIntakeStore } from '@/stores/intake-store';
import type { SubAgentId } from '@/types';
import { BrainCanvas } from './brain/canvas';
import { brainMockStream } from './brain/mock-stream';
import { DebriefCanvas } from './debrief/canvas';
import { debriefMockStream } from './debrief/mock-stream';
import { IntakeCanvas } from './intake/canvas';
import { SourcingCanvas } from './sourcing/canvas';
import { sourcingMockStream } from './sourcing/mock-stream';

export interface SubAgentModule {
  id: SubAgentId;
  Canvas: FC<{ id: string }>;
  mockStream: SubAgentMockStream;
}

// Adapter: the registry-level Canvas signature is FC<{ id: string }>, but
// IntakeCanvas needs the active sessionId (Phase 1 reads it from the intake
// store; a future /intake/sessions/[id] route will pass the URL param). This
// wrapper keeps the registry contract intact while letting tests pass the
// sessionId prop directly to IntakeCanvas.
const IntakeCanvasAdapter: FC<{ id: string }> = ({ id }) => {
  const sessionId = useIntakeStore((s) => s.sessionId);
  return <IntakeCanvas id={id} sessionId={sessionId} />;
};

export const SUB_AGENT_REGISTRY: Record<SubAgentId, SubAgentModule> = {
  intake: {
    id: 'intake',
    Canvas: IntakeCanvasAdapter,
    // Intake no longer uses the legacy mock-stream runner — the canvas
    // drives itself from useIntakeSession (Realtime + polling).
    mockStream: async function* () {},
  },
  debrief: {
    id: 'debrief',
    Canvas: DebriefCanvas,
    mockStream: (stage, input) =>
      debriefMockStream(stage as Parameters<typeof debriefMockStream>[0], input),
  },
  sourcing: {
    id: 'sourcing',
    Canvas: SourcingCanvas,
    mockStream: (stage, input) =>
      sourcingMockStream(stage as Parameters<typeof sourcingMockStream>[0], input),
  },
  brain: {
    id: 'brain',
    Canvas: BrainCanvas,
    mockStream: (stage, input) =>
      brainMockStream(stage as Parameters<typeof brainMockStream>[0], input),
  },
};
