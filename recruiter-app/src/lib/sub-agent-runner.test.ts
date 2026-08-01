import { describe, expect, test } from 'bun:test';
import type { StreamEvent } from './mock-stream';
import { createMockStream } from './mock-stream';
import { makeMessage, runStream } from './sub-agent-runner';

describe('sub-agent-runner', () => {
  test('runStream dispatches each event type to the matching hook', async () => {
    const script: StreamEvent[] = [
      { type: 'stage_start' },
      { type: 'prose_token', token: 'Hi' },
      { type: 'prose_token', token: ' there' },
      { type: 'sub_reveal', sub: 'hint' },
      { type: 'ux_reveal', component: 'chips', props: { a: 1 } },
      { type: 'artifact_start', artifactId: 'a', artifactType: 'requisition', title: 't' },
      { type: 'artifact_patch', artifactId: 'a', patch: { k: 'v' } },
      { type: 'artifact_complete', artifactId: 'a' },
      { type: 'stage_end', nextStage: 'next' },
    ];
    const tokens: string[] = [];
    const calls: string[] = [];
    let sub = '';
    let ux = '';
    let nextStage = '';
    let patchRecv: Record<string, unknown> = {};
    await runStream({
      stream: createMockStream(script, { speed: 0 }),
      onStageStart: () => {
        calls.push('stage_start');
      },
      onProseToken: (t) => {
        tokens.push(t);
      },
      onSubReveal: (s) => {
        sub = s;
      },
      onUxReveal: (component) => {
        ux = component;
      },
      onArtifactStart: (id, type, title) => {
        calls.push(`artifact_start:${id}:${type}:${title}`);
      },
      onArtifactPatch: (_id, patch) => {
        patchRecv = patch;
      },
      onArtifactComplete: (id) => {
        calls.push(`artifact_complete:${id}`);
      },
      onStageEnd: (s) => {
        nextStage = s;
      },
    });
    expect(tokens.join('')).toBe('Hi there');
    expect(sub).toBe('hint');
    expect(ux).toBe('chips');
    expect(nextStage).toBe('next');
    expect(patchRecv).toEqual({ k: 'v' });
    expect(calls).toEqual(['stage_start', 'artifact_start:a:requisition:t', 'artifact_complete:a']);
  });

  test('runStream still completes even when no hooks are set', async () => {
    const script: StreamEvent[] = [
      { type: 'stage_start' },
      { type: 'prose_token', token: 'x' },
      { type: 'stage_end', nextStage: 'done' },
    ];
    await runStream({ stream: createMockStream(script, { speed: 0 }) });
    // no error, test passes
    expect(true).toBe(true);
  });

  test('makeMessage creates a message with expected shape', () => {
    const msg = makeMessage('user', 'hello', 'voice');
    expect(msg.role).toBe('user');
    expect(msg.text).toBe('hello');
    expect(msg.mode).toBe('voice');
    expect(typeof msg.id).toBe('string');
    expect(msg.id.length).toBeGreaterThan(0);
    expect(new Date(msg.ts).toString()).not.toBe('Invalid Date');
  });

  test('makeMessage without mode omits the mode field', () => {
    const msg = makeMessage('agent', 'hi');
    expect(msg.mode).toBeUndefined();
  });
});
