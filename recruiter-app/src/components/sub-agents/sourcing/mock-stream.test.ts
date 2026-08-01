import { describe, expect, test } from 'bun:test';
import { parseQuery } from '@/fixtures/sourcing-queries';
import { detectSourcingIntent, SOURCING_ARTIFACT_ID, sourcingMockStream } from './mock-stream';

async function collect(stream: AsyncIterable<{ type: string }>) {
  const out: { type: string }[] = [];
  for await (const ev of stream) out.push(ev);
  return out;
}

describe('sourcingMockStream', () => {
  test('mode_pick asks about existing vs fresh', async () => {
    const events = await collect(sourcingMockStream('mode_pick', null, { speed: 0 }));
    const tokens = events
      .filter((e): e is { type: 'prose_token'; token: string } => e.type === 'prose_token')
      .map((e) => e.token)
      .join('');
    expect(tokens.toLowerCase()).toContain('existing role');
    expect(tokens.toLowerCase()).toContain('fresh');
    expect(events.at(-1)?.type).toBe('stage_end');
  });

  test('role_pick prompts for a role', async () => {
    const events = await collect(sourcingMockStream('role_pick', null, { speed: 0 }));
    const tokens = events
      .filter((e): e is { type: 'prose_token'; token: string } => e.type === 'prose_token')
      .map((e) => e.token)
      .join('');
    expect(tokens.toLowerCase()).toContain('which role');
    expect(events.find((e) => e.type === 'sub_reveal')).toBeDefined();
  });

  test('query_build encourages natural language and filter extraction', async () => {
    const events = await collect(sourcingMockStream('query_build', null, { speed: 0 }));
    const sub = events.find(
      (e): e is { type: 'sub_reveal'; sub: string } => e.type === 'sub_reveal',
    );
    expect(sub?.sub.toLowerCase()).toContain('filter pills');
  });

  test('results emits artifact_start, at least one artifact_patch, and artifact_complete', async () => {
    const criteria = parseQuery('Staff PMs in Sunnyvale with 7 years of experience');
    const ctx = JSON.stringify({ queryText: 'Staff PMs in Sunnyvale...', criteria });
    const events = await collect(sourcingMockStream('results', ctx, { speed: 0 }));
    const start = events.find(
      (e): e is { type: 'artifact_start'; artifactId: string; artifactType: string } =>
        e.type === 'artifact_start',
    );
    expect(start).toBeDefined();
    expect(start?.artifactId).toBe(SOURCING_ARTIFACT_ID);
    expect(start?.artifactType).toBe('sourcing-results');

    const patches = events.filter((e) => e.type === 'artifact_patch');
    expect(patches.length).toBeGreaterThanOrEqual(2);

    const complete = events.find((e) => e.type === 'artifact_complete');
    expect(complete).toBeDefined();
  });

  test('results with empty criteria still streams a seed + candidate patches', async () => {
    const ctx = JSON.stringify({ criteria: {} });
    const events = await collect(sourcingMockStream('results', ctx, { speed: 0 }));
    const patches = events.filter((e) => e.type === 'artifact_patch');
    expect(patches.length).toBeGreaterThanOrEqual(2);
  });
});

describe('detectSourcingIntent', () => {
  test('"refine filters" → refine_filters', () => {
    const o = detectSourcingIntent('please refine filters', 0);
    expect(o.kind).toBe('refine_filters');
    expect(o.response.length).toBeGreaterThan(0);
  });

  test('"add to pipeline" with 0 selected scolds the user', () => {
    const o = detectSourcingIntent('add to pipeline', 0);
    expect(o.kind).toBe('add_to_pipeline');
    expect(o.response.toLowerCase()).toContain('pick');
  });

  test('"add to pipeline" with 3 selected confirms the queue', () => {
    const o = detectSourcingIntent('add selected to pipeline now', 3);
    expect(o.kind).toBe('add_to_pipeline');
    expect(o.response).toContain('3 candidate');
  });

  test('"send outreach" with 2 selected drafts the batch', () => {
    const o = detectSourcingIntent('send outreach', 2);
    expect(o.kind).toBe('send_outreach');
    expect(o.response).toContain('2 candidate');
  });

  test('"export" acknowledges stub CSV', () => {
    const o = detectSourcingIntent('export as csv', 0);
    expect(o.kind).toBe('export');
    expect(o.response.toLowerCase()).toContain('export');
  });

  test('unknown input returns generic', () => {
    const o = detectSourcingIntent('hello sourcing', 0);
    expect(o.kind).toBe('generic');
  });
});
