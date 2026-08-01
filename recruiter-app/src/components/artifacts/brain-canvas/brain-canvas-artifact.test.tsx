import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { cleanup, fireEvent, render } from '@testing-library/react';
import { BRAIN_DEFAULT_RANGE, BRAIN_LINKS, BRAIN_NODES, BRAIN_STORIES } from '@/fixtures/brain';
import { useArtifactStore } from '@/stores';
import { BrainCanvasArtifact, type BrainCanvasArtifactData } from './brain-canvas-artifact';

const ARTIFACT_ID = 'bc-test';

function mkData(overrides: Partial<BrainCanvasArtifactData> = {}): BrainCanvasArtifactData {
  return {
    weekLabel: 'Week of Apr 14',
    timeRangeId: BRAIN_DEFAULT_RANGE,
    nodes: BRAIN_NODES,
    links: BRAIN_LINKS,
    stories: BRAIN_STORIES,
    mutedStoryIds: [],
    focusedNodeId: null,
    highlightedNodeIds: [],
    activeStoryId: null,
    ...overrides,
  };
}

function seed(data: BrainCanvasArtifactData) {
  useArtifactStore.getState().openArtifact({
    id: ARTIFACT_ID,
    type: 'brain-canvas',
    title: 'OpenRecruiting Brain',
    initialData: data,
  });
}

beforeEach(() => useArtifactStore.getState().reset());
afterEach(cleanup);

describe('BrainCanvasArtifact', () => {
  test('renders null when the artifact is absent', () => {
    const { container } = render(<BrainCanvasArtifact id="bc" artifactId="missing" />);
    expect(container.firstChild).toBeNull();
  });

  test('renders null when graph data is incomplete', () => {
    useArtifactStore.getState().openArtifact({
      id: ARTIFACT_ID,
      type: 'brain-canvas',
      title: 'pending',
      initialData: { weekLabel: 'x' },
    });
    const { container } = render(<BrainCanvasArtifact id="bc" artifactId={ARTIFACT_ID} />);
    expect(container.firstChild).toBeNull();
  });

  test('renders header stats, time-range chips, graph toolbar, and embedded force graph', () => {
    seed(mkData());
    const { container } = render(<BrainCanvasArtifact id="bc" artifactId={ARTIFACT_ID} />);

    expect(container.querySelector('#bc-headline')?.textContent).toContain('Week of Apr 14');
    expect(container.querySelector('#bc-stat-nodes')?.textContent).toContain(
      `${BRAIN_NODES.length} entities`,
    );
    expect(container.querySelector('#bc-stat-links')?.textContent).toContain(
      `${BRAIN_LINKS.length} relationships`,
    );

    // Filter chips + search + embedded force graph SVG.
    expect(container.querySelector('#bc-graph-filter-all')).not.toBeNull();
    expect(container.querySelector('#bc-graph-search-input')).not.toBeNull();
    expect(container.querySelector('#bc-graph-svg')).not.toBeNull();
  });

  test('renders one story card per (un-muted) story', () => {
    seed(mkData());
    const { container } = render(<BrainCanvasArtifact id="bc" artifactId={ARTIFACT_ID} />);
    for (const story of BRAIN_STORIES) {
      expect(container.querySelector(`#bc-story-${story.id}`)).not.toBeNull();
    }
  });

  test('muted stories are filtered out of the stories list', () => {
    const muted = BRAIN_STORIES[0];
    seed(mkData({ mutedStoryIds: muted ? [muted.id] : [] }));
    const { container } = render(<BrainCanvasArtifact id="bc" artifactId={ARTIFACT_ID} />);
    expect(container.querySelector(`#bc-story-${muted?.id}`)).toBeNull();
    expect(container.querySelector('#bc-stat-stories')?.textContent).toContain(
      `${BRAIN_STORIES.length - 1}`,
    );
  });

  test('range chips and node-type filter buttons fire callbacks', () => {
    seed(mkData());
    const ranges: string[] = [];
    const filters: (string | null)[] = [];
    const { container } = render(
      <BrainCanvasArtifact
        id="bc"
        artifactId={ARTIFACT_ID}
        onRangeChange={(r) => ranges.push(r)}
        onFilterType={(t) => filters.push(t)}
      />,
    );

    // Click a non-default range chip.
    fireEvent.click(container.querySelector('#bc-range-quarter') as Element);
    expect(ranges).toContain('quarter');

    fireEvent.click(container.querySelector('#bc-graph-filter-role') as Element);
    expect(filters).toContain('role');
  });

  test('story explain and mute buttons fire callbacks', () => {
    seed(mkData());
    const explained: string[] = [];
    const mutedClicks: string[] = [];
    const story = BRAIN_STORIES[0];
    const { container } = render(
      <BrainCanvasArtifact
        id="bc"
        artifactId={ARTIFACT_ID}
        onStoryExplain={(sid) => explained.push(sid)}
        onStoryMute={(sid) => mutedClicks.push(sid)}
      />,
    );
    fireEvent.click(container.querySelector(`#bc-story-${story?.id}-explain`) as Element);
    expect(explained).toContain(story?.id);
    fireEvent.click(container.querySelector(`#bc-story-${story?.id}-mute`) as Element);
    expect(mutedClicks).toContain(story?.id);
  });
});
