import { beforeEach, describe, expect, test } from 'bun:test';
import { useArtifactStore } from './artifact-store';

beforeEach(() => {
  useArtifactStore.getState().reset();
});

describe('artifact-store', () => {
  test('openArtifact creates an artifact with isBuilding true', () => {
    useArtifactStore.getState().openArtifact({
      id: 'a1',
      type: 'requisition',
      title: 'Staff PM',
      initialData: { rounds: [] },
    });
    const art = useArtifactStore.getState().artifacts.a1;
    expect(art).toBeDefined();
    expect(art?.type).toBe('requisition');
    expect(art?.isBuilding).toBe(true);
    expect(art?.expanded).toBe('default');
  });

  test('patchArtifact merges data shallowly', () => {
    useArtifactStore.getState().openArtifact({
      id: 'a1',
      type: 'requisition',
      title: 'Staff PM',
      initialData: { rounds: [] },
    });
    useArtifactStore.getState().patchArtifact('a1', { rounds: [{ n: 1, title: 'Screen' }] });
    const art = useArtifactStore.getState().artifacts.a1;
    expect((art?.data as { rounds: unknown[] }).rounds).toHaveLength(1);
  });

  test('completeArtifact flips isBuilding to false', () => {
    useArtifactStore.getState().openArtifact({
      id: 'a1',
      type: 'requisition',
      title: 'Staff PM',
      initialData: {},
    });
    useArtifactStore.getState().completeArtifact('a1');
    expect(useArtifactStore.getState().artifacts.a1?.isBuilding).toBe(false);
  });

  test('setExpanded updates expansion state', () => {
    useArtifactStore.getState().openArtifact({
      id: 'a1',
      type: 'comparative',
      title: 'Debrief',
      initialData: {},
    });
    useArtifactStore.getState().setExpanded('a1', 'expanded');
    expect(useArtifactStore.getState().artifacts.a1?.expanded).toBe('expanded');
  });

  test('removeArtifact deletes entry', () => {
    useArtifactStore.getState().openArtifact({
      id: 'a1',
      type: 'requisition',
      title: 'x',
      initialData: {},
    });
    useArtifactStore.getState().removeArtifact('a1');
    expect(useArtifactStore.getState().artifacts.a1).toBeUndefined();
  });

  test('reset clears all artifacts', () => {
    useArtifactStore.getState().openArtifact({
      id: 'a1',
      type: 'requisition',
      title: 'x',
      initialData: {},
    });
    useArtifactStore.getState().reset();
    expect(Object.keys(useArtifactStore.getState().artifacts)).toHaveLength(0);
  });
});

describe('requisition status', () => {
  beforeEach(() => useArtifactStore.getState().reset());

  test('openArtifact of type requisition seeds status: draft', () => {
    useArtifactStore.getState().openArtifact({
      id: 'r1',
      type: 'requisition',
      title: 'Test',
      initialData: {},
    });
    expect(useArtifactStore.getState().artifacts.r1?.status).toBe('draft');
  });

  test('publishArtifact flips status to active', () => {
    useArtifactStore.getState().openArtifact({
      id: 'r1',
      type: 'requisition',
      title: 'Test',
      initialData: {},
    });
    useArtifactStore.getState().publishArtifact('r1');
    expect(useArtifactStore.getState().artifacts.r1?.status).toBe('active');
  });

  test('archiveArtifact flips status to archived', () => {
    useArtifactStore.getState().openArtifact({
      id: 'r1',
      type: 'requisition',
      title: 'Test',
      initialData: {},
    });
    useArtifactStore.getState().archiveArtifact('r1');
    expect(useArtifactStore.getState().artifacts.r1?.status).toBe('archived');
  });

  test('expandArtifact sets expanded to expanded (fullscreen)', () => {
    useArtifactStore.getState().openArtifact({
      id: 'r1',
      type: 'requisition',
      title: 'Test',
      initialData: {},
    });
    useArtifactStore.getState().expandArtifact('r1');
    expect(useArtifactStore.getState().artifacts.r1?.expanded).toBe('expanded');
  });

  test('collapseArtifact returns to default', () => {
    useArtifactStore.getState().openArtifact({
      id: 'r1',
      type: 'requisition',
      title: 'Test',
      initialData: {},
    });
    useArtifactStore.getState().expandArtifact('r1');
    useArtifactStore.getState().collapseArtifact('r1');
    expect(useArtifactStore.getState().artifacts.r1?.expanded).toBe('default');
  });
});
