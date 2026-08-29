import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { cleanup, render } from '@testing-library/react';
import { type FeedbackPacket, getPacket } from '@/fixtures/feedback-packets';
import { useArtifactStore } from '@/stores';
import { FeedbackPacketArtifact } from './feedback-packet-artifact';

const ARTIFACT_ID = 'fp-test';
const PACKET = getPacket('pm-sfo', 'c1') as FeedbackPacket;

function seed(data: Record<string, unknown>, isBuilding = false) {
  useArtifactStore.getState().openArtifact({
    id: ARTIFACT_ID,
    type: 'packet',
    title: 'Feedback packet',
    initialData: data,
  });
  if (!isBuilding) useArtifactStore.getState().completeArtifact(ARTIFACT_ID);
}

beforeEach(() => useArtifactStore.getState().reset());
afterEach(cleanup);

describe('FeedbackPacketArtifact', () => {
  test('renders null when the artifact is absent', () => {
    const { container } = render(<FeedbackPacketArtifact id="fp" artifactId="missing" />);
    expect(container.firstChild).toBeNull();
  });

  test('renders the header, summary, digest and a card per round from a full packet', () => {
    seed({ ...PACKET });
    const { container } = render(<FeedbackPacketArtifact id="fp" artifactId={ARTIFACT_ID} />);

    expect(container.querySelector('#fp')).not.toBeNull();
    expect(container.querySelector('#fp-headline')?.textContent).toContain(PACKET.candidateName);
    // strong verdict label (Sloane is a strong-hire fixture).
    expect(container.querySelector('#fp-verdict-label')?.textContent).toBe('Strong hire');
    expect(container.querySelector('#fp-summary-prose')?.textContent).toContain(
      PACKET.overall.summary.slice(0, 12),
    );

    // Three-column digest sections.
    expect(container.querySelector('#fp-digest-strengths')).not.toBeNull();
    expect(container.querySelector('#fp-digest-watchouts')).not.toBeNull();
    expect(container.querySelector('#fp-digest-next')).not.toBeNull();

    // One round card per packet round.
    for (const round of PACKET.rounds) {
      const card = container.querySelector(`#fp-round-${round.id}`);
      expect(card).not.toBeNull();
      expect(card?.textContent).toContain(round.title);
    }

    // Static actions footer is present.
    expect(container.querySelector('#fp-footer-actions')).not.toBeNull();
  });

  test('renders panelists strip when panelistsPanel is present', () => {
    seed({
      ...PACKET,
      panelistsPanel: [
        { name: 'Dana Cho', role: 'Eng Lead', score: 3.8 },
        { name: 'Sam Lee', role: 'Design', score: 3.2 },
      ],
    });
    const { container } = render(<FeedbackPacketArtifact id="fp" artifactId={ARTIFACT_ID} />);
    expect(container.querySelector('#fp-panelists')).not.toBeNull();
    expect(container.querySelector('#fp-panelist-0-name')?.textContent).toContain('Dana Cho');
  });

  test('renders the recommended-additional and reply-draft branches when set', () => {
    seed({
      ...PACKET,
      recommendedAdditional: {
        title: 'System design deep-dive',
        rationale: 'Confirm scaling judgment before offer.',
      },
      replyDraft: { open: true, body: 'Thanks for the thorough feedback…' },
    });
    const { container } = render(<FeedbackPacketArtifact id="fp" artifactId={ARTIFACT_ID} />);
    expect(container.querySelector('#fp-recommended-body')?.textContent).toContain(
      'Confirm scaling judgment',
    );
    expect(
      (container.querySelector('#fp-reply-textarea') as HTMLTextAreaElement | null)?.value,
    ).toContain('Thanks for the thorough feedback');
  });

  test('flagged round shows the flag badge; building shows the streaming note', () => {
    const flaggedRound = PACKET.rounds[0];
    seed({ ...PACKET, flagged: true, flaggedRoundId: flaggedRound?.id ?? null }, true);
    const { container } = render(<FeedbackPacketArtifact id="fp" artifactId={ARTIFACT_ID} />);
    expect(container.querySelector('#fp-flag-badge')).not.toBeNull();
    expect(container.querySelector('#fp-building')?.textContent).toContain('Streaming rounds');
  });
});
