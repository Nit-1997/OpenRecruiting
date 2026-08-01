// Pure policy helpers for the intake voice call lifecycle. Extracted so the
// mute-on-resume + agent-state decisions are unit-testable without mounting the
// pipecat WebRTC provider (which can't establish a PeerConnection in happy-dom).

export type AgentState = 'listening' | 'thinking' | 'speaking';

/**
 * Whether the mic should be ENABLED when the call resumes from a pause.
 *
 * Before FE-J5 resume() force-enabled the mic, silently un-muting a recruiter
 * who had muted before pausing. The mic must honor the persisted mute intent:
 * resume mic = NOT muted.
 */
export function micShouldEnableOnResume(isMuted: boolean): boolean {
  return !isMuted;
}

/**
 * Map a pipecat bot/user speaking signal to the coarse agent state the UI shows.
 * The provider wires these via the RTVI callbacks (onBotStartedSpeaking, etc.).
 */
export function nextAgentState(
  event:
    | 'bot_started_speaking'
    | 'bot_stopped_speaking'
    | 'bot_llm_started'
    | 'user_started_speaking',
): AgentState {
  switch (event) {
    case 'bot_started_speaking':
      return 'speaking';
    case 'bot_llm_started':
      return 'thinking';
    default:
      // bot stopped, or the user started talking → the agent is listening.
      return 'listening';
  }
}
