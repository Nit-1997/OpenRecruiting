import { describe, expect, it } from 'bun:test';
import { micShouldEnableOnResume, nextAgentState } from '../voice-mic-policy';

describe('micShouldEnableOnResume (FE-J5 honor mute on resume)', () => {
  it('keeps the mic OFF when the call was muted before pausing', () => {
    expect(micShouldEnableOnResume(true)).toBe(false);
  });

  it('re-enables the mic when the call was NOT muted', () => {
    expect(micShouldEnableOnResume(false)).toBe(true);
  });
});

describe('nextAgentState (FE-J5 wire dead agentState)', () => {
  it('maps bot started speaking → speaking', () => {
    expect(nextAgentState('bot_started_speaking')).toBe('speaking');
  });
  it('maps bot llm started → thinking', () => {
    expect(nextAgentState('bot_llm_started')).toBe('thinking');
  });
  it('maps bot stopped speaking → listening', () => {
    expect(nextAgentState('bot_stopped_speaking')).toBe('listening');
  });
  it('maps user started speaking → listening', () => {
    expect(nextAgentState('user_started_speaking')).toBe('listening');
  });
});
