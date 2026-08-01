/**
 * Render tests for the debrief packet view (toolbar + body). The view
 * is purely presentational — it receives a `DebriefPacket` and renders.
 * We exercise the render path with a real fixture so the conditional
 * branches (verdict styles, panel votes, themes, decision matrix, risks)
 * all get walked.
 */

import { afterEach, describe, expect, mock, test } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import {
  DEBRIEF_PACKETS,
  type DebriefCandidateSnapshot,
  type DebriefDecisionRow,
  type DebriefPacket,
} from '@/fixtures/debrief-packets';
import { DebriefPacketBody, DebriefPacketToolbar, VERDICT_STYLE, VOTE_STYLE } from './packet-view';

const ORIGINAL_PRINT = globalThis.print;

afterEach(() => {
  cleanup();
  globalThis.print = ORIGINAL_PRINT;
});

function firstPacket(): DebriefPacket {
  const all = Object.values(DEBRIEF_PACKETS).flat();
  const p = all[0];
  if (!p) throw new Error('expected DEBRIEF_PACKETS to seed at least one packet');
  return p;
}

describe('DebriefPacketToolbar — single Download action (spec §3 B.1 / Task 2.2)', () => {
  test('renders exactly one Download action that prints in place (not a route link)', () => {
    const packet = firstPacket();
    const printMock = mock(() => {});
    globalThis.print = printMock as unknown as typeof globalThis.print;

    render(<DebriefPacketToolbar id="dp" packet={packet} />);

    const download = document.getElementById('dp-download');
    expect(download).not.toBeNull();
    // The download is an in-place print button, NOT a link to a print route.
    expect(download?.tagName).toBe('BUTTON');
    expect(download?.getAttribute('href')).toBeNull();
    expect(download?.textContent).toContain('Download');

    // Clicking it fires window.print() (browser dialog → Save as PDF).
    fireEvent.click(download as Element);
    expect(printMock.mock.calls.length).toBe(1);

    // The actions strip carries exactly one control (the Download button).
    const actions = document.getElementById('dp-toolbar-actions');
    expect(actions?.querySelectorAll('a, button').length).toBe(1);
  });

  test('the Download action does not link to the (deleted) /debrief/print route', () => {
    const packet = firstPacket();
    render(<DebriefPacketToolbar id="dp" packet={packet} />);
    // No anchor anywhere in the actions strip points at the removed route.
    const actions = document.getElementById('dp-toolbar-actions');
    expect(actions?.querySelector('a[href^="/debrief/print"]')).toBeNull();
  });

  test('the old Share / Export PDF / copy-link controls are gone', () => {
    const packet = firstPacket();
    render(<DebriefPacketToolbar id="dp" packet={packet} />);
    expect(document.getElementById('dp-share')).toBeNull();
    expect(document.getElementById('dp-export')).toBeNull();
    expect(document.getElementById('dp-copy')).toBeNull();
    expect(screen.queryByText('Export PDF')).toBeNull();
    expect(screen.queryByText('Copy link')).toBeNull();
  });
});

describe('DebriefPacketToolbar', () => {
  test('renders without crashing with a real fixture packet', () => {
    const packet = firstPacket();
    const { container } = render(<DebriefPacketToolbar id="dp" packet={packet} />);
    // Render path completes; the toolbar produces a non-empty subtree.
    expect(container.firstChild).not.toBeNull();
  });

  test('renders trailing slot when provided', () => {
    const packet = firstPacket();
    render(
      <DebriefPacketToolbar
        id="dp"
        packet={packet}
        trailing={
          <button type="button" data-testid="trailing-action">
            Action
          </button>
        }
      />,
    );
    expect(screen.getByTestId('trailing-action')).toBeDefined();
  });

  test('renders all four verdict styles in the lookup map', () => {
    // Pin the map shape — adding a new verdict must update both the type
    // and the styles or the lookup will throw at runtime.
    expect(VERDICT_STYLE.strong_hire).toBeDefined();
    expect(VERDICT_STYLE.hire).toBeDefined();
    expect(VERDICT_STYLE.mixed).toBeDefined();
    expect(VERDICT_STYLE.no_hire).toBeDefined();
  });

  test('renders all five vote styles in the lookup map', () => {
    expect(VOTE_STYLE.strong_yes).toBeDefined();
    expect(VOTE_STYLE.yes).toBeDefined();
    expect(VOTE_STYLE.maybe).toBeDefined();
    expect(VOTE_STYLE.no).toBeDefined();
    expect(VOTE_STYLE.strong_no).toBeDefined();
  });
});

describe('DebriefPacketBody', () => {
  test('renders the headline recommendation and verdict', () => {
    const packet = firstPacket();
    render(<DebriefPacketBody id="dp" packet={packet} />);
    // Headline appears somewhere in the body.
    expect(
      screen.queryAllByText(new RegExp(packet.headline_recommendation.slice(0, 24))).length,
    ).toBeGreaterThan(0);
  });

  test('renders every candidate snapshot by name', () => {
    const packet = firstPacket();
    render(<DebriefPacketBody id="dp" packet={packet} />);
    for (const c of packet.candidates) {
      expect(screen.queryAllByText(new RegExp(c.name)).length).toBeGreaterThan(0);
    }
  });

  test('renders the decision matrix rows when present', () => {
    const packet = firstPacket();
    render(<DebriefPacketBody id="dp" packet={packet} />);
    for (const row of packet.decision_matrix) {
      expect(screen.queryAllByText(new RegExp(row.dimension)).length).toBeGreaterThan(0);
    }
  });

  test('renders each risk line', () => {
    const packet = firstPacket();
    const firstRisk = packet.risks[0];
    if (!firstRisk) return; // skip if fixture has no risks
    render(<DebriefPacketBody id="dp" packet={packet} />);
    expect(screen.queryAllByText(new RegExp(firstRisk.slice(0, 16))).length).toBeGreaterThan(0);
  });

  // BUG C: the non-functional "push back" affordance is removed. The header copy
  // advertising a score-click interaction must be gone, and the rubric score
  // cells must NOT advertise a "click to push back" interaction that does
  // nothing. The score values themselves still render.
  test('no "push back" copy in the header and no clickable push-back score cells', () => {
    const packet = firstPacket();
    render(<DebriefPacketBody id="dp" packet={packet} />);

    expect(screen.queryByText(/push back/i)).toBeNull();
    expect(screen.queryByText(/re-weigh/i)).toBeNull();
    // No score cell advertises the (dead) push-back interaction via title.
    expect(document.querySelector('[title="Click to push back on this score"]')).toBeNull();
  });
});

describe('DebriefPacketBody — rubric missing-score cell (FIX 2 / spec §4 D6)', () => {
  function snapshot(id: string, name: string, rank: number): DebriefCandidateSnapshot {
    return {
      candidate_id: id,
      name,
      initials: name
        .split(' ')
        .map((p) => p[0])
        .join(''),
      color: '#EADFD4',
      rank,
      verdict: 'hire',
      headline: `${name} headline`,
      aggregate_score: 3.2,
      score_scale: 4,
      rounds_completed: 4,
      rounds_total: 4,
      top_strengths: [],
      top_concerns: [],
      recommendation: `Advance ${name}.`,
      panel_votes: [],
    };
  }

  // A row whose scores map OMITS one candidate's key. The renderer must paint
  // the dashed em-dash placeholder for the missing cell and NEVER a literal '0'
  // (the two-sided "never render 0 for a missing cell" contract). The present
  // cell must paint its score + winner highlight.
  function packetWithMissingCell(): DebriefPacket {
    const row: DebriefDecisionRow = {
      dimension: 'Product judgment',
      scores: { c1: 4 }, // c2 deliberately omitted
      winner_ids: ['c1'],
      note: 'Only one candidate has signal on this axis.',
    };
    return {
      id: 'pkt-missing',
      requisition_id: 'r1',
      role_title: 'Staff PM',
      title: 'Staff PM debrief',
      subtitle: 'Comparison',
      generated_at: '2026-04-16T18:45:00Z',
      generated_by: 'OpenRecruiting debrief agent',
      status: 'fresh',
      panel_members: [],
      candidates: [snapshot('c1', 'Priya Natarajan', 1), snapshot('c2', 'Marcus Chen', 2)],
      headline_recommendation: 'Advance Priya.',
      verdict: 'hire',
      confidence: 'high',
      source_stats: { scorecards: 8, transcripts: 2 },
      themes: [],
      decision_matrix: [row],
      risks: [],
      next_steps: [],
    };
  }

  test('a missing candidate score renders the em-dash placeholder, never a literal 0', () => {
    render(<DebriefPacketBody id="dp" packet={packetWithMissingCell()} />);

    // The dashed placeholder cell renders a bare em-dash for the omitted score.
    const dashes = screen.getAllByText('—');
    expect(dashes.length).toBeGreaterThan(0);
    // The missing cell carries the dashed-border placeholder styling.
    const placeholder = dashes.find((el) => el.className.includes('border-dashed'));
    expect(placeholder).toBeDefined();

    // The omission must NEVER be coerced into a rendered '0' anywhere in the body.
    expect(screen.queryByText('0')).toBeNull();
    expect(screen.queryByText('0.0/4')).toBeNull();
    expect(screen.queryByText('0.0')).toBeNull();
  });

  test('a present candidate score paints its value + winner highlight', () => {
    render(<DebriefPacketBody id="dp" packet={packetWithMissingCell()} />);

    // c1's present score renders as a clickable cell showing the value...
    const cell = document.getElementById('dp-rubric-row-Product judgment-score-c1');
    expect(cell).not.toBeNull();
    expect(cell?.textContent).toContain('4.0/4');

    // ...and winner_ids highlighting actually paints (the Winner checkmark).
    expect(screen.getByLabelText('Winner')).toBeDefined();
  });

  // The winner tick must read in BOTH light and dark mode. The old style used
  // `bg-white/80` — the ONE opacity the dark-mode shim in globals.css skips —
  // plus `text-text-primary`, which flips to near-white in dark → invisible.
  // The fix is a mode-independent indicator (white circle, fixed-hue green
  // check) that contrasts on the green winner bar regardless of theme.
  test('the winner indicator uses a mode-independent class (not bg-white/80)', () => {
    render(<DebriefPacketBody id="dp" packet={packetWithMissingCell()} />);
    const indicator = screen.getByLabelText('Winner');
    // The fixed-hue indicator is present...
    expect(indicator.className).toContain('bg-white');
    expect(indicator.className).toContain('text-emerald-600');
    // ...and the broken opacity / flipping token are gone.
    expect(indicator.className).not.toContain('bg-white/80');
    expect(indicator.className).not.toContain('text-text-primary');
  });
});

describe('DebriefPacketToolbar — draft status (generate->preview->Save loop)', () => {
  // Generate now lands a `draft` the FE previews before committing via Save. A
  // draft packet must type cleanly (status: 'draft') and render WITHOUT the
  // 'Superseded' badge (that badge fires only on === 'superseded').
  function draftPacket(): DebriefPacket {
    return { ...firstPacket(), status: 'draft' };
  }

  test('a draft packet renders without crashing and shows no Superseded badge', () => {
    render(<DebriefPacketToolbar id="dp" packet={draftPacket()} />);
    expect(document.getElementById('dp-toolbar')).not.toBeNull();
    expect(screen.queryByText('Superseded')).toBeNull();
  });

  test('a superseded packet still shows the Superseded badge (no regression)', () => {
    render(<DebriefPacketToolbar id="dp" packet={{ ...firstPacket(), status: 'superseded' }} />);
    expect(screen.queryByText('Superseded')).not.toBeNull();
  });
});

describe('DebriefPacketBody — aggregate_insufficient (BUG 2 / spec §5)', () => {
  function snapshot(
    id: string,
    name: string,
    rank: number,
    insufficient: boolean,
  ): DebriefCandidateSnapshot {
    return {
      candidate_id: id,
      name,
      initials: name
        .split(' ')
        .map((p) => p[0])
        .join(''),
      color: '#EADFD4',
      rank,
      verdict: 'hire',
      headline: `${name} headline`,
      // Zero scorable cells → 0.0 sentinel; the flag drives the FE render.
      aggregate_score: insufficient ? 0.0 : 3.2,
      score_scale: 4,
      rounds_completed: 1,
      rounds_total: 1,
      top_strengths: [],
      top_concerns: [],
      recommendation: `Advance ${name}.`,
      panel_votes: [],
      aggregate_insufficient: insufficient,
    };
  }

  function packetWithInsufficientCandidate(): DebriefPacket {
    return {
      id: 'pkt-insufficient',
      requisition_id: 'r1',
      role_title: 'Product Manager',
      title: 'Product Manager debrief',
      subtitle: 'Baseline · 2 candidates compared',
      generated_at: '2026-06-07T18:45:00Z',
      generated_by: 'OpenRecruiting debrief agent',
      status: 'fresh',
      panel_members: [],
      // c1 has signal, c2 has zero scorable cells (insufficient).
      candidates: [snapshot('c1', 'Ada Lovelace', 1, false), snapshot('c2', 'Solo Cand', 2, true)],
      headline_recommendation: 'Advance Ada.',
      verdict: 'hire',
      confidence: 'low',
      source_stats: { scorecards: 1, transcripts: 1 },
      themes: [],
      decision_matrix: [],
      risks: [],
      next_steps: [],
    };
  }

  test('an insufficient candidate shows "Insufficient signal", never the 0.0 aggregate', () => {
    render(<DebriefPacketBody id="dp" packet={packetWithInsufficientCandidate()} />);

    // The insufficient label appears (matrix header + candidate panel).
    expect(screen.getAllByText(/Insufficient signal/).length).toBeGreaterThan(0);

    // The 0.0 sentinel must NEVER surface as a fabricated score.
    expect(screen.queryByText('0.0')).toBeNull();
    expect(screen.queryByText(/Weighted 0\.0 \/ 4\.0/)).toBeNull();
  });

  test('a candidate WITH signal still shows its weighted aggregate (no false positive)', () => {
    render(<DebriefPacketBody id="dp" packet={packetWithInsufficientCandidate()} />);
    // c1 (sufficient) keeps its real weighted score.
    expect(screen.getAllByText(/Weighted 3\.2 \/ 4\.0/).length).toBeGreaterThan(0);
  });
});
