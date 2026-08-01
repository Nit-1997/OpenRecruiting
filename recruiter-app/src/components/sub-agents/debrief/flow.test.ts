import { beforeEach, describe, expect, test } from 'bun:test';
import type { RoleFixture } from '@/fixtures/roles';
import { useArtifactStore, useSessionStore } from '@/stores';
import {
  cancelCandidatePick,
  completeAnalyzing,
  confirmCandidatePick,
  pickDebriefRole,
  toggleCandidate,
} from './flow';
import { DEBRIEF_ARTIFACT_ID } from './mock-stream';

const DEMO_ROLE: RoleFixture = {
  id: 'pm-sfo',
  title: 'Staff PM · Sunnyvale',
  loc: 'Full-time · Product',
  pipeline: '4 candidates awaiting decision',
  status: 'live',
  dept: 'Product',
  owner: 'Nitin',
  created_at: '2026-03-22T14:30:00Z',
  ready_to_debrief: true,
  must_have: [],
  nice_to_have: [],
};

beforeEach(() => {
  useSessionStore.getState().reset();
  useArtifactStore.getState().reset();
  if (typeof localStorage !== 'undefined') localStorage.clear();
});

describe('debrief flow', () => {
  test('pickDebriefRole starts a session, echoes user msg, advances to candidate_pick', async () => {
    await pickDebriefRole(DEMO_ROLE);
    const s = useSessionStore.getState().sessions.debrief;
    expect(s?.stage).toBe('candidate_pick');
    expect(s?.selections.roleId).toBe('pm-sfo');
    expect(s?.selections.roleTitle).toBe('Staff PM · Sunnyvale');
    const userMsg = s?.messages.find((m) => m.role === 'user');
    expect(userMsg?.text).toContain('debrief');
  });

  test('toggleCandidate adds then removes the candidate id', async () => {
    await pickDebriefRole(DEMO_ROLE);
    toggleCandidate('c1');
    toggleCandidate('c2');
    let sel = useSessionStore.getState().sessions.debrief?.selections
      .selectedCandidates as string[];
    expect(sel).toEqual(['c1', 'c2']);
    toggleCandidate('c1');
    sel = useSessionStore.getState().sessions.debrief?.selections.selectedCandidates as string[];
    expect(sel).toEqual(['c2']);
  });

  test('confirmCandidatePick requires 2+ candidates', async () => {
    await pickDebriefRole(DEMO_ROLE);
    toggleCandidate('c1');
    await confirmCandidatePick({ speed: 0 });
    // Still in candidate_pick — we didn't satisfy the threshold.
    expect(useSessionStore.getState().sessions.debrief?.stage).toBe('candidate_pick');
  });

  test('confirmCandidatePick advances to analyzing with 2+ candidates', async () => {
    await pickDebriefRole(DEMO_ROLE);
    toggleCandidate('c1');
    toggleCandidate('c2');
    await confirmCandidatePick({ speed: 0 });
    const s = useSessionStore.getState().sessions.debrief;
    expect(s?.stage).toBe('analyzing');
  });

  test('completeAnalyzing seeds the comparative artifact + advances to result', async () => {
    await pickDebriefRole(DEMO_ROLE);
    toggleCandidate('c1');
    toggleCandidate('c2');
    await confirmCandidatePick({ speed: 0 });
    await completeAnalyzing({ speed: 0 });
    const s = useSessionStore.getState().sessions.debrief;
    expect(s?.stage).toBe('result');
    const art = useArtifactStore.getState().artifacts[DEBRIEF_ARTIFACT_ID];
    expect(art).toBeDefined();
    expect(art?.type).toBe('comparative');
    const data = art?.data as { candidateIds?: string[] };
    expect(data.candidateIds).toEqual(['c1', 'c2']);
  });

  test('cancelCandidatePick clears selections + returns to role_pick', async () => {
    await pickDebriefRole(DEMO_ROLE);
    toggleCandidate('c1');
    cancelCandidatePick();
    const s = useSessionStore.getState().sessions.debrief;
    expect(s?.stage).toBe('role_pick');
    expect((s?.selections.selectedCandidates as string[]).length).toBe(0);
  });
});
