export const SUB_AGENT_IDS = ['intake', 'sourcing', 'debrief', 'brain'] as const;

export type SubAgentId = (typeof SUB_AGENT_IDS)[number];

export const SUB_AGENT_LABELS: Record<SubAgentId, string> = {
  intake: 'Intake Agent',
  sourcing: 'Sourcing Agent',
  debrief: 'Debrief Agent',
  brain: 'Insights Agent',
};

export type StageId = string;

export type ChatTabId = SubAgentId | 'home';

export type CortexMessageBlock =
  | { kind: 'paragraph'; text: string }
  | { kind: 'bullets'; items: string[] }
  | { kind: 'quote'; text: string; cite: string };

export interface CortexMessagePayload {
  who: string;
  blocks: CortexMessageBlock[];
  chips?: Array<{ label: string; value: string; primary?: boolean }>;
}

/** A propose-tool payload streamed by the debrief chat agent (spec §5). `kind`
 *  is the propose TOOL name (e.g. `propose_add_round`); `input` always carries
 *  `candidate_ids`/`summary`/`rationale` plus kind-specific fields. Sent back
 *  verbatim to the `/actions` execute endpoint. */
export interface ProposedAction {
  kind: string;
  input: {
    candidate_ids: string[];
    summary: string;
    rationale: string;
    [k: string]: unknown;
  };
}

/** Render state for a confirm-card message: awaiting a decision, executing,
 *  applied, dismissed, or failed. */
export type ConfirmStatus = 'pending' | 'executing' | 'done' | 'failed' | 'dismissed';

export interface Message {
  id: string;
  role: 'agent' | 'user';
  text: string;
  mode?: 'text' | 'voice';
  ts: string;
  source: 'scripted' | 'chat';
  chips?: Array<{ label: string; value: string; primary?: boolean }>;
  /** Optional subtitle, rendered under the message headline when this message
   *  renders in display variant (typically the first agent greeting).       */
  sub?: string;
  /** If present, the transcript renders this message as a rich Cortex card
   *  (stage 05 insights), instead of the default AgentMsg bubble.            */
  cortex?: CortexMessagePayload;
  /** If present, the transcript renders this message as an inline Cortex
   *  thinking-trail card, backed by an artifact-store entry that ticks
   *  step-by-step. Used when the visual analysis lives on the right.        */
  cortexTrail?: { artifactId: string };
  /** If present, the transcript renders this message as a debrief-packet
   *  reference card with an "Open packet" action, so a closed packet can be
   *  reopened from the chat at any time. `packetId` is the backend row id
   *  (null on the mock path, where only the in-store artifact can reopen).  */
  packetRef?: { packetId: string | null; roleTitle: string };
  /** If present, the transcript renders this message as a debrief confirm card
   *  (Confirm / Dismiss) for the proposed action it carries.                */
  confirmAction?: ProposedAction;
  /** Live state of a `confirmAction` card, patched in place via the store as
   *  the recruiter confirms/dismisses and the execute call resolves.        */
  confirmStatus?: ConfirmStatus;
}

export interface Session {
  id: string;
  startedAt: string;
  lastActiveAt: string;
  stage: StageId;
  messages: Message[];
  selections: Record<string, unknown>;
  artifactId: string | null;
  artifactHistory: string[];
  status: 'fresh' | 'active' | 'completed' | 'paused';
}
