// Debrief candidate-picker gating + signal display (spec §7).
//
// The picker is a CONTROLLED component (`selected` + `onToggle` are props), so we
// drive it from a tiny React-state harness that mirrors real usage — no store or
// fetch needed at this layer (the backend→FE mapper that carries signal/eligibility
// is covered in lib/debrief/api.test.ts against a mocked globalThis.fetch).
//
// Asserts: not-ready candidates render disabled + with a reason and can't be
// toggled into the selection; ready candidates show their signal; the confirm CTA
// is disabled until >= 2 READY are selected and enabled at 2.

import { afterEach, describe, expect, test } from 'bun:test';
import { cleanup, fireEvent, render } from '@testing-library/react';
import { useState } from 'react';
import type { CandidateFixture } from '@/fixtures/candidates';
import { CandidatePicker } from './candidate-picker';

afterEach(cleanup);

function readyCandidate(
  id: string,
  name: string,
  signal: { feedback_count: number; evidence_backed_count: number },
): CandidateFixture {
  return {
    id,
    name,
    role: '',
    stage: 'Ready to debrief',
    rounds: 4,
    scoresIn: 4,
    avatar: name.slice(0, 2).toUpperCase(),
    color: '#EADFD4',
    flag: '4/4 rounds',
    status: 'ready',
    eligibility: 'ready',
    signal,
  };
}

const READY_A = readyCandidate('cr1', 'Ada Lovelace', {
  feedback_count: 3,
  evidence_backed_count: 2,
});
const READY_B = readyCandidate('cr2', 'Grace Hopper', {
  feedback_count: 4,
  evidence_backed_count: 4,
});
const AWAITING: CandidateFixture = {
  id: 'cw1',
  name: 'Marcus Wait',
  role: '',
  stage: 'Awaiting signal',
  rounds: 4,
  scoresIn: 1,
  avatar: 'MW',
  color: '#D8EFE3',
  flag: '1/4 rounds',
  status: 'waiting',
  eligibility: 'awaiting_signal',
  signal: { feedback_count: 0, evidence_backed_count: 0 },
};
const EARLY: CandidateFixture = {
  id: 'ce1',
  name: 'Early Bird',
  role: '',
  stage: 'Early stage',
  rounds: 4,
  scoresIn: 0,
  avatar: 'EB',
  color: '#E9DFF5',
  flag: '0/4 rounds',
  status: 'early',
  eligibility: 'early_stage',
  signal: { feedback_count: 0, evidence_backed_count: 0 },
};

const ALL = [READY_A, READY_B, AWAITING, EARLY];

/** Controlled harness holding the selection, exactly as the real stage wires it. */
function Harness({ candidates }: { candidates: CandidateFixture[] }) {
  const [selected, setSelected] = useState<string[]>([]);
  return (
    <CandidatePicker
      id="cp"
      reqId="req-1"
      roleTitle="Staff PM"
      selected={selected}
      candidates={candidates}
      onToggle={(cid) =>
        setSelected((prev) => (prev.includes(cid) ? prev.filter((x) => x !== cid) : [...prev, cid]))
      }
      onConfirm={() => {}}
      onCancel={() => {}}
    />
  );
}

function confirmBtn(): HTMLButtonElement {
  return document.getElementById('cp-confirm') as HTMLButtonElement;
}

describe('CandidatePicker — not-ready candidates are gated', () => {
  test('awaiting_signal renders disabled, with a reason, and is NOT a button', () => {
    render(<Harness candidates={ALL} />);
    const card = document.getElementById('cp-card-cw1');
    expect(card).not.toBeNull();
    // Rendered as a non-interactive div, not a <button>.
    expect(card?.tagName.toLowerCase()).toBe('div');
    expect(card?.getAttribute('aria-disabled')).toBe('true');
    const reason = document.getElementById('cp-card-cw1-reason');
    expect(reason?.textContent).toBe('No feedback yet');
  });

  test('early_stage shows the no-completed-rounds reason', () => {
    render(<Harness candidates={ALL} />);
    const reason = document.getElementById('cp-card-ce1-reason');
    expect(reason?.textContent).toBe('No completed rounds');
  });

  test('clicking a not-ready card does not select it (no toggle handler)', () => {
    render(<Harness candidates={ALL} />);
    const card = document.getElementById('cp-card-cw1') as HTMLElement;
    fireEvent.click(card);
    // The meta line counts ready-selected; it stays at 0.
    const meta = document.getElementById('cp-meta');
    expect(meta?.textContent).toContain('0 ready selected');
  });
});

describe('CandidatePicker — ready candidates show signal', () => {
  test('ready card renders the "N scorecards · M evidence-backed" line', () => {
    render(<Harness candidates={ALL} />);
    const sig = document.getElementById('cp-card-cr1-signal');
    expect(sig?.textContent).toBe('3 scorecards · 2 evidence-backed');
  });

  test('singular scorecard is pluralized correctly', () => {
    const one = readyCandidate('cr3', 'Solo One', {
      feedback_count: 1,
      evidence_backed_count: 1,
    });
    render(<Harness candidates={[one, READY_A]} />);
    const sig = document.getElementById('cp-card-cr3-signal');
    expect(sig?.textContent).toBe('1 scorecard · 1 evidence-backed');
  });
});

describe('CandidatePicker — confirm gate counts only READY selected', () => {
  test('CTA is disabled with zero selected', () => {
    render(<Harness candidates={ALL} />);
    expect(confirmBtn().disabled).toBe(true);
  });

  test('CTA stays disabled at 1 ready selected, enables at 2', () => {
    render(<Harness candidates={ALL} />);
    fireEvent.click(document.getElementById('cp-card-cr1') as HTMLElement);
    expect(confirmBtn().disabled).toBe(true);
    fireEvent.click(document.getElementById('cp-card-cr2') as HTMLElement);
    expect(confirmBtn().disabled).toBe(false);
    expect(confirmBtn().textContent).toContain('2');
  });
});

describe('CandidatePicker — round-count parity gate', () => {
  const FOUR_A = {
    ...readyCandidate('cr1', 'Ada', { feedback_count: 3, evidence_backed_count: 2 }),
    ratedRounds: 4,
  };
  const FOUR_B = {
    ...readyCandidate('cr2', 'Grace', { feedback_count: 4, evidence_backed_count: 4 }),
    ratedRounds: 4,
  };
  const ONE = {
    ...readyCandidate('cr3', 'Zara', { feedback_count: 1, evidence_backed_count: 1 }),
    ratedRounds: 1,
  };

  function disabled(id: string): boolean {
    return (document.getElementById(id) as HTMLButtonElement).disabled;
  }

  test('all ready candidates are selectable before anything is picked', () => {
    render(<Harness candidates={[FOUR_A, FOUR_B, ONE]} />);
    expect(disabled('cp-card-cr1')).toBe(false);
    expect(disabled('cp-card-cr3')).toBe(false);
  });

  test('selecting a 4-round candidate disables a 1-round candidate, keeps a 4-round one', () => {
    render(<Harness candidates={[FOUR_A, FOUR_B, ONE]} />);
    fireEvent.click(document.getElementById('cp-card-cr1') as HTMLElement); // anchor = 4
    expect(disabled('cp-card-cr3')).toBe(true); // 1 rated round ≠ 4
    expect(disabled('cp-card-cr2')).toBe(false); // 4 rated rounds matches
    expect(document.getElementById('cp-card-cr3-signal')?.textContent).toContain(
      'Needs 4 rated rounds',
    );
  });

  test('a parity-mismatched card cannot be toggled into the selection', () => {
    render(<Harness candidates={[FOUR_A, ONE]} />);
    fireEvent.click(document.getElementById('cp-card-cr1') as HTMLElement); // anchor = 4
    fireEvent.click(document.getElementById('cp-card-cr3') as HTMLElement); // mismatched → ignored
    expect(document.getElementById('cp-meta')?.textContent).toContain('1 ready selected');
  });

  test('deselecting clears the anchor so all ready are selectable again', () => {
    render(<Harness candidates={[FOUR_A, ONE]} />);
    fireEvent.click(document.getElementById('cp-card-cr1') as HTMLElement); // select → anchor 4
    expect(disabled('cp-card-cr3')).toBe(true);
    fireEvent.click(document.getElementById('cp-card-cr1') as HTMLElement); // deselect → no anchor
    expect(disabled('cp-card-cr3')).toBe(false);
  });
});
