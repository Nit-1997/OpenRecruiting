import { afterEach, describe, expect, test } from 'bun:test';
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import { BRAIN_LINKS, BRAIN_NODES } from '@/fixtures/brain';
import { ForceGraph } from './force-graph';

// A small, deterministic slice of the real graph. The d3-force simulation
// settles asynchronously (it ticks via requestAnimationFrame, which happy-dom
// provides), so node circles appear after the first tick → waitFor.
const NODES = BRAIN_NODES.slice(0, 4);
const LINKS = BRAIN_LINKS.filter(
  (l) => NODES.some((n) => n.id === l.source) && NODES.some((n) => n.id === l.target),
);

afterEach(cleanup);

describe('ForceGraph', () => {
  test('renders the SVG shell, background and grid immediately', () => {
    const { container } = render(
      <ForceGraph
        id="fg"
        nodes={NODES}
        links={LINKS}
        focusedNodeId={null}
        highlightedNodeIds={[]}
        onNodeClick={() => {}}
      />,
    );
    expect(container.querySelector('#fg')?.tagName.toLowerCase()).toBe('svg');
    expect(container.querySelector('#fg-bg')).not.toBeNull();
    expect(container.querySelector('#fg-grid')).not.toBeNull();
    expect(container.querySelector('#fg-nodes')).not.toBeNull();
    expect(container.querySelector('#fg-links')).not.toBeNull();
  });

  test('renders a node group per node once the simulation ticks', async () => {
    const { container } = render(
      <ForceGraph
        id="fg"
        nodes={NODES}
        links={LINKS}
        focusedNodeId={null}
        highlightedNodeIds={[]}
        onNodeClick={() => {}}
      />,
    );
    await waitFor(() => {
      expect(container.querySelectorAll('#fg-nodes > g').length).toBe(NODES.length);
    });
    // Each node renders its core circle.
    for (const n of NODES) {
      expect(container.querySelector(`#fg-node-${n.id}-core`)).not.toBeNull();
    }
  });

  test('activating a node via keyboard fires onNodeClick', async () => {
    let clicked: string | null = null;
    const { container } = render(
      <ForceGraph
        id="fg"
        nodes={NODES}
        links={LINKS}
        focusedNodeId={NODES[0]?.id ?? null}
        highlightedNodeIds={[NODES[0]?.id ?? '']}
        onNodeClick={(node) => {
          clicked = node.id;
        }}
      />,
    );
    let group: Element | null = null;
    await waitFor(() => {
      group = container.querySelector(`#fg-node-${NODES[0]?.id}`);
      expect(group).not.toBeNull();
    });
    // Nodes are activated via Enter (the group is role="button", tabIndex=0).
    fireEvent.keyDown(group as unknown as Element, { key: 'Enter' });
    expect(clicked).toBe(NODES[0]?.id);
  });

  test('clicking the SVG background fires onBackgroundClick', () => {
    let bgClicked = 0;
    const { container } = render(
      <ForceGraph
        id="fg"
        nodes={NODES}
        links={LINKS}
        focusedNodeId={null}
        highlightedNodeIds={[]}
        onNodeClick={() => {}}
        onBackgroundClick={() => {
          bgClicked += 1;
        }}
      />,
    );
    // onBackgroundClick fires only when the click target is the SVG itself.
    const svg = container.querySelector('#fg') as Element;
    fireEvent.click(svg, { target: svg });
    expect(bgClicked).toBe(1);
  });
});
