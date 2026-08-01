import { describe, expect, test } from 'bun:test';
import { BRAIN_NODES, BRAIN_STORIES } from '@/fixtures/brain';
import { BRAIN_ARTIFACT_ID, brainMockStream, detectBrainIntent, labelForNode } from './mock-stream';

async function collect(stream: AsyncIterable<{ type: string }>) {
  const out: { type: string }[] = [];
  for await (const ev of stream) out.push(ev);
  return out;
}

describe('brainMockStream', () => {
  test('emits stage_start, artifact_start, artifact_patch, artifact_complete, stage_end', async () => {
    const events = await collect(brainMockStream('brain', null, { speed: 0 }));
    const types = events.map((e) => e.type);
    expect(types).toContain('stage_start');
    expect(types).toContain('artifact_start');
    expect(types.filter((t) => t === 'artifact_patch').length).toBeGreaterThanOrEqual(1);
    expect(types).toContain('artifact_complete');
    expect(types.at(-1)).toBe('stage_end');
  });

  test('artifact_start emits the right artifact id + type', async () => {
    const events = await collect(brainMockStream('brain', null, { speed: 0 }));
    const start = events.find(
      (e): e is { type: 'artifact_start'; artifactId: string; artifactType: string } =>
        e.type === 'artifact_start',
    );
    expect(start?.artifactId).toBe(BRAIN_ARTIFACT_ID);
    expect(start?.artifactType).toBe('brain-canvas');
  });

  test('artifact_patch seeds nodes, links, and stories', async () => {
    const events = await collect(brainMockStream('brain', null, { speed: 0 }));
    const patches = events.filter(
      (e): e is { type: 'artifact_patch'; artifactId: string; patch: Record<string, unknown> } =>
        e.type === 'artifact_patch',
    );
    expect(patches.length).toBeGreaterThanOrEqual(1);
    const first = patches[0];
    const patch = first?.patch ?? {};
    const nodes = patch.nodes as unknown[] | undefined;
    const links = patch.links as unknown[] | undefined;
    const stories = patch.stories as unknown[] | undefined;
    expect(nodes?.length).toBe(BRAIN_NODES.length);
    expect(links?.length).toBeGreaterThan(0);
    expect(stories?.length).toBe(BRAIN_STORIES.length);
  });

  test('parses weekLabel from context json', async () => {
    const events = await collect(
      brainMockStream('brain', JSON.stringify({ weekLabel: 'Week of April 6' }), { speed: 0 }),
    );
    const start = events.find(
      (
        e,
      ): e is { type: 'artifact_start'; artifactId: string; title: string; artifactType: string } =>
        e.type === 'artifact_start',
    );
    expect(start?.title.toLowerCase()).toContain('week of april 6');
  });
});

describe('detectBrainIntent', () => {
  test('empty input falls through with guidance', () => {
    const outcome = detectBrainIntent('   ');
    expect(outcome.kind).toBe('generic');
    expect(outcome.response.toLowerCase()).toContain('explain');
  });

  test('"explain scoring drift" picks the drift story and focuses its target nodes', () => {
    const outcome = detectBrainIntent('explain scoring drift');
    expect(outcome.kind).toBe('explain_story');
    expect(outcome.storyId).toBe('story-scoring-drift');
    expect(outcome.focusNodeIds?.length).toBeGreaterThan(0);
  });

  test('"drill into Ben" focuses the Ben interviewer node', () => {
    const outcome = detectBrainIntent('drill into Ben');
    expect(outcome.kind).toBe('drill_node');
    expect(outcome.nodeId).toBe('i-ben');
  });

  test('"what is causing pipeline risk" returns the pipeline story with evidence in the response', () => {
    const outcome = detectBrainIntent('what is causing pipeline risk');
    expect(outcome.kind).toBe('cause_query');
    expect(outcome.storyId).toBe('story-pipeline-risk');
    expect(outcome.response.toLowerCase()).toContain('candidates awaiting');
  });

  test('"compare Q1 to Q2" returns the compare stub', () => {
    const outcome = detectBrainIntent('compare Q1 to Q2');
    expect(outcome.kind).toBe('compare');
    expect(outcome.response.toLowerCase()).toContain('quarter');
  });

  test('"mute panel load" mutes the panel overload story', () => {
    const outcome = detectBrainIntent('mute panel load');
    expect(outcome.kind).toBe('mute_story');
    expect(outcome.storyId).toBe('story-panel-overload');
    expect(outcome.mute).toBe(true);
  });

  test('"stories" lists all tracked stories', () => {
    const outcome = detectBrainIntent('what stories are you tracking');
    expect(outcome.kind).toBe('list_stories');
    for (const s of BRAIN_STORIES) {
      expect(outcome.response).toContain(s.title);
    }
  });

  test('"clear" resets focus', () => {
    const outcome = detectBrainIntent('clear');
    expect(outcome.kind).toBe('reset');
    expect(outcome.response.toLowerCase()).toContain('cleared');
  });

  test('unknown input falls through gracefully', () => {
    const outcome = detectBrainIntent('xyz unrelated query');
    expect(outcome.kind).toBe('generic');
  });

  test('labelForNode resolves known node ids', () => {
    expect(labelForNode('i-ben').toLowerCase()).toContain('ben');
    expect(labelForNode('r-pm-sfo').toLowerCase()).toContain('staff pm');
  });

  test('labelForNode returns raw id for unknown', () => {
    expect(labelForNode('unknown-id')).toBe('unknown-id');
  });
});
