import { describe, expect, test } from 'bun:test';
import { DEBRIEF_ARTIFACT_ID, debriefMockStream } from './mock-stream';

async function collect(stream: AsyncIterable<{ type: string }>) {
  const out: { type: string }[] = [];
  for await (const ev of stream) out.push(ev);
  return out;
}

describe('debriefMockStream', () => {
  test('role_pick asks which role + sub reveal', async () => {
    const events = await collect(debriefMockStream('role_pick', null, { speed: 0 }));
    const tokens = events
      .filter((e): e is { type: 'prose_token'; token: string } => e.type === 'prose_token')
      .map((e) => e.token)
      .join('');
    expect(tokens.toLowerCase()).toContain('which role');
    expect(events.find((e) => e.type === 'sub_reveal')).toBeDefined();
    expect(events.at(-1)?.type).toBe('stage_end');
  });

  test('candidate_pick includes the role title when provided', async () => {
    const ctx = JSON.stringify({ roleTitle: 'Staff PM · Sunnyvale' });
    const events = await collect(debriefMockStream('candidate_pick', ctx, { speed: 0 }));
    const tokens = events
      .filter((e): e is { type: 'prose_token'; token: string } => e.type === 'prose_token')
      .map((e) => e.token)
      .join('');
    expect(tokens).toContain('Staff PM · Sunnyvale');
  });

  test('analyzing references the candidate names', async () => {
    const ctx = JSON.stringify({ candidateNames: ['Priya', 'Marcus', 'Rivka'] });
    const events = await collect(debriefMockStream('analyzing', ctx, { speed: 0 }));
    const tokens = events
      .filter((e): e is { type: 'prose_token'; token: string } => e.type === 'prose_token')
      .map((e) => e.token)
      .join('');
    expect(tokens).toContain('Priya');
    expect(tokens).toContain('Marcus');
    expect(tokens).toContain('Rivka');
  });

  test('result emits artifact patch + complete + chip row', async () => {
    const ctx = JSON.stringify({
      roleTitle: 'Staff PM · Sunnyvale',
      candidateNames: ['Priya'],
    });
    const events = await collect(debriefMockStream('result', ctx, { speed: 0 }));
    const patch = events.find((e) => e.type === 'artifact_patch') as unknown as {
      type: 'artifact_patch';
      artifactId: string;
    };
    expect(patch).toBeDefined();
    expect(patch.artifactId).toBe(DEBRIEF_ARTIFACT_ID);
    const complete = events.find((e) => e.type === 'artifact_complete') as unknown as {
      type: 'artifact_complete';
      artifactId: string;
    };
    expect(complete).toBeDefined();
    expect(complete.artifactId).toBe(DEBRIEF_ARTIFACT_ID);
    const ux = events.find((e) => e.type === 'ux_reveal') as unknown as {
      type: 'ux_reveal';
      component: string;
    };
    expect(ux.component).toBe('debrief_result_chips');
  });
});
