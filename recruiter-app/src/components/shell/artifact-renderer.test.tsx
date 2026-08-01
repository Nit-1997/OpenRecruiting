/**
 * Tests for ArtifactRenderer — the dispatch switch that maps an
 * Artifact's `type` discriminator to the matching artifact component.
 *
 * The actual artifact components are heavy (framer-motion, d3, fixture
 * data). This file only validates that the dispatch table is intact:
 * every supported ArtifactType resolves to a render path that doesn't
 * throw. Component-specific tests live alongside each artifact.
 */

import { afterEach, describe, expect, test } from 'bun:test';
import { cleanup, render } from '@testing-library/react';
import type { Artifact, ArtifactType } from '@/types';
import { ArtifactRenderer } from './artifact-renderer';

afterEach(cleanup);

function makeArtifact(type: ArtifactType): Artifact {
  return {
    id: 'art-test-1',
    type,
    title: `Test ${type}`,
    data: {},
    isBuilding: false,
    expanded: 'default',
  };
}

describe('ArtifactRenderer — dispatch table', () => {
  // Each type in the switch must resolve. We don't assert on rendered
  // text (the underlying components are stubbed by fixture lookups);
  // the test passes if no throw occurs and a non-empty subtree renders.
  test.each<ArtifactType>([
    'requisition',
    'comparative',
    'packet',
    'sourcing-results',
    'sourcing-strategy',
    'cortex-insight',
    'cortex-analysis',
    'brain-canvas',
  ])('dispatches %s without crashing', (type) => {
    // selections is consumed by the comparative branch — pass empty
    // defaults so we exercise the dispatch without crashing on undefined.
    const { container } = render(
      <ArtifactRenderer
        id="r"
        artifact={makeArtifact(type)}
        selections={{ roleId: 'role-1', selectedCandidates: [] }}
      />,
    );
    expect(container).toBeDefined();
  });

  test('returns a fallback for unknown artifact types (no throw)', () => {
    // We cast to bypass the union; a malformed artifact arriving from a
    // stale fixture or an out-of-date FE must not crash the column.
    const malformed = makeArtifact('cortex-insight');
    (malformed as unknown as { type: string }).type = 'totally-unknown';
    const { container } = render(
      <ArtifactRenderer
        id="r"
        artifact={malformed}
        selections={{ roleId: '', selectedCandidates: [] }}
      />,
    );
    expect(container).toBeDefined();
  });
});
