/**
 * Render tests for the role-tab PacketCard (spec §3 B.3 / Task 2.4). The card's
 * standalone Download (previously a link to the separate print route) was
 * removed: downloading now happens inside the packet drawer's toolbar after
 * "Open packet" (in-place window.print()). The open-drawer overlay button — the
 * card's primary affordance — stays. The earlier per-row copy-link (broken
 * `reqId=''` URL on thin v2 rows) and `.txt` stub remain gone.
 */

import { afterEach, describe, expect, test } from 'bun:test';
import { cleanup, render } from '@testing-library/react';
import type { ComponentType } from 'react';
import type { PacketRow } from './debrief-tab';

// role-detail-page.test.tsx stubs `./debrief-tab` process-wide (bun's
// mock.module is last-writer-wins), which would strip the genuine `PacketCard`
// from a static import. Read the real export via the test-setup snapshot
// (mirrors plan-tab.test.tsx's `__REAL_PLAN_TAB__`).
const { PacketCard } =
  (
    globalThis as {
      __REAL_DEBRIEF_TAB__?: {
        PacketCard: ComponentType<{ id: string; row: PacketRow; onOpen: () => void }>;
      };
    }
  ).__REAL_DEBRIEF_TAB__ ?? require('./debrief-tab');

afterEach(cleanup);

function thinRow(overrides: Partial<PacketRow> = {}): PacketRow {
  return {
    id: 'pkt-abc',
    verdict: 'hire',
    status: 'fresh',
    candidateCount: 3,
    generatedAt: '2026-06-07T18:45:00Z',
    title: 'Debrief packet',
    subtitle: null,
    headline: null,
    full: null,
    ...overrides,
  };
}

describe('PacketCard — download moved into the drawer (Task 2.4)', () => {
  test('the standalone per-row Download link is gone', () => {
    render(<PacketCard id="dt-packet-pkt-abc" row={thinRow()} onOpen={() => {}} />);
    // The card no longer carries its own download control; downloading happens
    // in the drawer toolbar after the card is opened.
    expect(document.getElementById('dt-packet-pkt-abc-download')).toBeNull();
  });

  test('no card control links to the (deleted) /debrief/print route', () => {
    const { container } = render(
      <PacketCard id="dt-packet-pkt-abc" row={thinRow()} onOpen={() => {}} />,
    );
    expect(container.querySelector('a[href^="/debrief/print"]')).toBeNull();
  });

  test('the broken copy-link control is gone', () => {
    render(<PacketCard id="dt-packet-pkt-abc" row={thinRow()} onOpen={() => {}} />);
    expect(document.getElementById('dt-packet-pkt-abc-copy')).toBeNull();
  });

  test('the open-drawer overlay button is preserved', () => {
    render(<PacketCard id="dt-packet-pkt-abc" row={thinRow()} onOpen={() => {}} />);
    const open = document.getElementById('dt-packet-pkt-abc-open');
    expect(open).not.toBeNull();
    expect(open?.tagName).toBe('BUTTON');
  });
});
