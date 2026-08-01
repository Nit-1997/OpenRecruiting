// FIX 1 — the analyzing stage must resolve candidate display metadata from the
// REAL v2 pool the picker stashed in `session.selections.candidatePool`, not the
// static fixture. Under v2 the selected ids are real candidate UUIDs that the
// fixture lookup (`getCandidatesByIds`) returns [] for — which used to render no
// avatars + blank <em> names.
//
// We drive the REAL component + REAL session store (reset in beforeEach). We do
// NOT mock `../flow` (a process-wide `mock.module` would corrupt the genuine
// `completeAnalyzing` for the concurrent flow.v2 tests). The animation's onDone
// only fires after ~2.4s of `useEffect` timers; the synchronous render + immediate
// assertion below never advances them, so no real flow work runs.

import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { cleanup, render } from '@testing-library/react';
import type { CandidateFixture } from '@/fixtures/candidates';
import { useSessionStore } from '@/stores';
import { AnalyzingStage } from './analyzing';

// Real candidate UUIDs (NOT the fixture's c1/c2 ids) — the fixture lookup
// returns [] for these, so a passing render proves the pool was used.
const V2_POOL: CandidateFixture[] = [
  {
    id: '7b1f0c2e-aaaa-4f00-9000-000000000001',
    name: 'Aanya Rao',
    role: '',
    stage: 'Ready to debrief',
    rounds: 4,
    scoresIn: 4,
    avatar: 'AR',
    color: '#EADFD4',
    flag: '4/4 rounds',
    status: 'ready',
  },
  {
    id: '7b1f0c2e-bbbb-4f00-9000-000000000002',
    name: 'Bruno Whitaker',
    role: '',
    stage: 'Ready to debrief',
    rounds: 4,
    scoresIn: 4,
    avatar: 'BW',
    color: '#D8EFE3',
    flag: '4/4 rounds',
    status: 'ready',
  },
];

beforeEach(() => {
  useSessionStore.getState().reset();
});

afterEach(cleanup);

describe('AnalyzingStage — resolves candidate meta from the v2 pool (FIX 1)', () => {
  test('renders the real candidate first-names + avatar initials from candidatePool', () => {
    const store = useSessionStore.getState();
    store.startSession('debrief', 'analyzing');
    store.updateSelections('debrief', {
      roleId: 'req-uuid-123',
      roleTitle: 'Staff PM',
      selectedCandidates: V2_POOL.map((c) => c.id),
      candidatePool: V2_POOL,
    });

    render(<AnalyzingStage id="dbrf-analyzing" />);

    // First-names joined as the animated <em> title — non-empty + correct.
    const names = document.getElementById('dbrf-analyzing-title-names');
    expect(names?.textContent).toBe('Aanya · Bruno');

    // Avatar initials painted (not empty) for both pooled candidates.
    const a0 = document.getElementById('dbrf-analyzing-avatar-0-initials');
    const a1 = document.getElementById('dbrf-analyzing-avatar-1-initials');
    expect(a0?.textContent).toBe('AR');
    expect(a1?.textContent).toBe('BW');
  });

  // BUG B: the analyzing animation capped avatars at 3 (`.slice(0, 3)`), so a
  // 4-candidate debrief lost an avatar. The debrief supports 2–5 candidates —
  // ALL selected candidates' avatars must render.
  test('renders ALL avatars for a 4-candidate debrief (no 3-cap)', () => {
    const pool: CandidateFixture[] = [
      { ...V2_POOL[0], id: 'p1', name: 'Aanya Rao', avatar: 'AR' } as CandidateFixture,
      { ...V2_POOL[0], id: 'p2', name: 'Bruno Whitaker', avatar: 'BW' } as CandidateFixture,
      { ...V2_POOL[0], id: 'p3', name: 'Chloe Diaz', avatar: 'CD' } as CandidateFixture,
      { ...V2_POOL[0], id: 'p4', name: 'Devon Park', avatar: 'DP' } as CandidateFixture,
    ];
    const store = useSessionStore.getState();
    store.startSession('debrief', 'analyzing');
    store.updateSelections('debrief', {
      roleId: 'req-uuid-123',
      roleTitle: 'Staff PM',
      selectedCandidates: pool.map((c) => c.id),
      candidatePool: pool,
    });

    render(<AnalyzingStage id="dbrf-analyzing" />);

    const avatarRow = document.getElementById('dbrf-analyzing-avatars');
    // Four avatar wrappers (each has the `-avatar-N` id), not three.
    const avatars = avatarRow?.querySelectorAll('[id^="dbrf-analyzing-avatar-"]');
    const wrappers = Array.from(avatars ?? []).filter((el) =>
      /^dbrf-analyzing-avatar-\d+$/.test(el.id),
    );
    expect(wrappers.length).toBe(4);
    expect(document.getElementById('dbrf-analyzing-avatar-3-initials')?.textContent).toBe('DP');
  });
});
