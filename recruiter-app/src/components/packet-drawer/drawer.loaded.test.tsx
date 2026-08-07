/**
 * Loaded-state coverage for PacketDrawer.
 *
 * The existing drawer.smoke.test.tsx only exercises the null/loading render
 * states (packet + requisition === null). This file drives the *populated*
 * path: a real seeded packet (4 completed rounds with feedback) is fed in via
 * spyOn(usePacket), so the round rail, RoundPane, evaluation criteria, the
 * pane tabs, and the lazy RecordingSection all render and exercise their
 * branches.
 *
 * Spies are installed per-test and restored after so other files keep the real
 * hooks (the cross-file isolation contract in test-setup.ts).
 */

import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  spyOn,
  test,
} from 'bun:test';
import { cleanup, fireEvent, render } from '@testing-library/react';
import { ConfirmDialogProvider } from '@/components/ui/confirm-dialog';
import type { RoundRecording } from '@/domain';
import * as services from '@/hooks/use-services';
import type { CandidatePacket } from '@/services/candidates';
import * as candidateSvc from '@/services/candidates';
import { clearDb } from '@/services/mock-db';
import { seedDb } from '@/services/seed';
import { PacketDrawer } from './drawer';

let PACKET: CandidatePacket;

beforeAll(async () => {
  clearDb();
  seedDb();
  PACKET = await candidateSvc.getPacket('pm-sfo', 'pm-sfo_c1');
});

afterAll(() => clearDb());

let packetSpy: ReturnType<typeof spyOn> | null = null;
let reqSpy: ReturnType<typeof spyOn> | null = null;
let recordingSpy: ReturnType<typeof spyOn> | null = null;

function asyncState<T>(data: T) {
  return { data, loading: false, error: null, refetch: () => {} } as unknown as ReturnType<
    typeof services.usePacket
  >;
}

// PacketDrawer calls useConfirm() (round cancel), which requires the provider.
function renderDrawer(ui: Parameters<typeof render>[0]) {
  return render(<ConfirmDialogProvider>{ui}</ConfirmDialogProvider>);
}

beforeEach(() => {
  packetSpy = spyOn(services, 'usePacket').mockReturnValue(asyncState(PACKET));
  reqSpy = spyOn(services, 'useRequisition').mockReturnValue(
    asyncState({ role_title: 'Staff PM · Sunnyvale' }),
  );
  recordingSpy = spyOn(services, 'useRecording').mockReturnValue(asyncState(null));
});

afterEach(() => {
  packetSpy?.mockRestore();
  reqSpy?.mockRestore();
  recordingSpy?.mockRestore();
  cleanup();
});

describe('PacketDrawer — loaded packet', () => {
  test('renders the candidate header with email, role title and round count', () => {
    const { container } = renderDrawer(
      <PacketDrawer
        id="pd"
        reqId="pm-sfo"
        candidateId="pm-sfo_c1"
        initialRoundId={null}
        onClose={() => {}}
      />,
    );
    expect(container.querySelector('#pd-title')?.textContent).toBe('Priya Natarajan');
    const sub = document.querySelector('#pd aside p.text-text-muted')?.textContent ?? '';
    expect(sub).toContain('Staff PM · Sunnyvale');
    expect(sub).toContain('4 rounds');
  });

  test('round rail renders one button per round and auto-selects the first', () => {
    const { container } = renderDrawer(
      <PacketDrawer
        id="pd"
        reqId="pm-sfo"
        candidateId="pm-sfo_c1"
        initialRoundId={null}
        onClose={() => {}}
      />,
    );
    const rail = container.querySelector('#pd-rail');
    expect(rail).not.toBeNull();
    for (const entry of PACKET.rounds) {
      expect(container.querySelector(`#pd-rail-round-${entry.round.id}`)).not.toBeNull();
    }
    // First round auto-selected → its pane renders with the round title.
    const pane = container.querySelector('#pd-pane');
    expect(pane).not.toBeNull();
    expect(pane?.textContent).toContain(PACKET.rounds[0]?.round.name ?? '');
  });

  test('selecting a different round swaps the pane content', () => {
    const { container } = renderDrawer(
      <PacketDrawer
        id="pd"
        reqId="pm-sfo"
        candidateId="pm-sfo_c1"
        initialRoundId={null}
        onClose={() => {}}
      />,
    );
    const second = PACKET.rounds[1];
    fireEvent.click(container.querySelector(`#pd-rail-round-${second?.round.id}`) as Element);
    expect(container.querySelector('#pd-pane')?.textContent).toContain(second?.round.name ?? '');
  });

  test('pane tabs toggle between feedback packet and round replay', () => {
    const { container } = renderDrawer(
      <PacketDrawer
        id="pd"
        reqId="pm-sfo"
        candidateId="pm-sfo_c1"
        initialRoundId={null}
        onClose={() => {}}
      />,
    );
    expect(container.querySelector('#pd-pane-tab-packet')).not.toBeNull();
    expect(container.querySelector('#pd-pane-tab-replay')).not.toBeNull();
    // Switch to replay → the recording section (lazy) mounts.
    fireEvent.click(container.querySelector('#pd-pane-tab-replay') as Element);
    expect(container.querySelector('#pd-pane-recording')).not.toBeNull();
  });

  test('Escape key and the close button both invoke onClose', () => {
    let closed = 0;
    const { container } = renderDrawer(
      <PacketDrawer
        id="pd"
        reqId="pm-sfo"
        candidateId="pm-sfo_c1"
        initialRoundId={null}
        onClose={() => {
          closed += 1;
        }}
      />,
    );
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(closed).toBe(1);

    // The backdrop close button (aria-label="Close packet").
    const closeBtn = container.querySelector('button[aria-label="Close packet"]');
    fireEvent.click(closeBtn as Element);
    expect(closed).toBe(2);
  });

  test('viewOnly mode suppresses the add-custom-round affordance', () => {
    const { container } = renderDrawer(
      <PacketDrawer
        id="pd"
        reqId="pm-sfo"
        candidateId="pm-sfo_c1"
        initialRoundId={null}
        viewOnly
        onClose={() => {}}
      />,
    );
    // No "Add custom round" button in the rail when view-only.
    expect(container.querySelector('#pd-rail-add-round')).toBeNull();
  });

  test('opening the add-custom-round dialog renders the form fields', () => {
    const { container } = renderDrawer(
      <PacketDrawer
        id="pd"
        reqId="pm-sfo"
        candidateId="pm-sfo_c1"
        initialRoundId={null}
        onClose={() => {}}
      />,
    );
    const addBtn = container.querySelector('#pd-rail-add-round');
    expect(addBtn).not.toBeNull();
    fireEvent.click(addBtn as Element);
    // Dialog mounts with a name field.
    expect(document.querySelector('#pd-rail-add-form-name')).not.toBeNull();
  });
});

describe('PacketDrawer — replay tab with an available recording', () => {
  const RECORDING: RoundRecording = {
    candidate_round_id: 'pm-sfo_c1_pm-sfo_round_1',
    recording_url: 'https://example.com/replay.mp4',
    transcript_excerpt: 'Thanks for joining…',
    transcript_segments: [
      { start_seconds: 0, end_seconds: 18, speaker: 'Interviewer', text: 'Walk me through it.' },
      { start_seconds: 18, end_seconds: 40, speaker: 'Priya Natarajan', text: 'I led the launch.' },
      { start_seconds: 40, end_seconds: 65, speaker: 'Interviewer', text: 'How did you measure?' },
    ],
    duration_seconds: 120,
    feedback_start_seconds: 80,
    available: true,
  };

  beforeEach(() => {
    recordingSpy?.mockRestore();
    recordingSpy = spyOn(services, 'useRecording').mockReturnValue(asyncState(RECORDING));
  });

  test('renders the player, segment tabs and the full transcript on the replay tab', () => {
    const { container } = renderDrawer(
      <PacketDrawer
        id="pd"
        reqId="pm-sfo"
        candidateId="pm-sfo_c1"
        initialRoundId={null}
        onClose={() => {}}
      />,
    );
    fireEvent.click(container.querySelector('#pd-pane-tab-replay') as Element);

    const recording = container.querySelector('#pd-pane-recording');
    expect(recording).not.toBeNull();
    // feedback_start_seconds < duration → interview/feedback segment tabs render.
    expect(container.querySelector('#pd-pane-recording-segments')).not.toBeNull();
    // Transcript viewer renders every segment's text.
    expect(recording?.textContent).toContain('Walk me through it.');
    expect(recording?.textContent).toContain('I led the launch.');
  });

  test('switching to the feedback segment tab does not crash and keeps the transcript', () => {
    const { container } = renderDrawer(
      <PacketDrawer
        id="pd"
        reqId="pm-sfo"
        candidateId="pm-sfo_c1"
        initialRoundId={null}
        onClose={() => {}}
      />,
    );
    fireEvent.click(container.querySelector('#pd-pane-tab-replay') as Element);
    fireEvent.click(container.querySelector('#pd-pane-recording-segment-feedback') as Element);
    // Transcript stays visible regardless of the active segment.
    expect(container.querySelector('#pd-pane-recording')?.textContent).toContain(
      'How did you measure?',
    );
  });
});

describe('PacketDrawer — replay tab gating on unscheduled rounds', () => {
  test('disables the Round replay tab for a pending (not scheduled) round', () => {
    const pendingPacket = structuredClone(PACKET);
    const first = pendingPacket.rounds[0];
    if (first?.candidate_round) first.candidate_round.status = 'pending';
    packetSpy?.mockReturnValue(asyncState(pendingPacket));

    const { container } = renderDrawer(
      <PacketDrawer
        id="pd"
        reqId="pm-sfo"
        candidateId="pm-sfo_c1"
        initialRoundId={null}
        onClose={() => {}}
      />,
    );
    const replayTab = container.querySelector('#pd-pane-tab-replay') as HTMLButtonElement;
    expect(replayTab).not.toBeNull();
    expect(replayTab.disabled).toBe(true);
  });

  test('keeps the Round replay tab enabled for a completed round', () => {
    // The seeded PACKET rounds are completed.
    const { container } = renderDrawer(
      <PacketDrawer
        id="pd"
        reqId="pm-sfo"
        candidateId="pm-sfo_c1"
        initialRoundId={null}
        onClose={() => {}}
      />,
    );
    const replayTab = container.querySelector('#pd-pane-tab-replay') as HTMLButtonElement;
    expect(replayTab.disabled).toBe(false);
  });

  test('scorecard stat counts questions answered, never raw feedback points', () => {
    // Regression: the seed writes 3 feedback points per question, so the old
    // numerator (raw entry count) overshot the question total — e.g. "12 / 4".
    // The stat must be "questions answered / total questions" (numerator never
    // exceeds the denominator).
    const { container } = renderDrawer(
      <PacketDrawer
        id="pd"
        reqId="pm-sfo"
        candidateId="pm-sfo_c1"
        initialRoundId={null}
        onClose={() => {}}
      />,
    );
    const stat = container.querySelector('#pd-pane-context-scorecard');
    expect(stat).not.toBeNull();
    const match = (stat?.textContent ?? '').match(/(\d+)\s*\/\s*(\d+)/);
    expect(match).not.toBeNull();
    const answered = Number(match?.[1]);
    const total = Number(match?.[2]);
    // The auto-selected first round is completed with feedback on every
    // question → fully answered, not "3× total".
    expect(answered).toBeLessThanOrEqual(total);
    expect(total).toBeGreaterThan(0);
    expect(answered).toBe(total);
    expect(stat?.textContent).toContain('All questions answered');
  });
});
