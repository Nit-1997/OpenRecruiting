import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { cleanup, fireEvent, render } from '@testing-library/react';
import { CORTEX_INSIGHTS } from '@/fixtures/cortex-insights';
import { useArtifactStore } from '@/stores';
import { CortexAnalysisArtifact } from './cortex-analysis-artifact';
import type { CortexAnalysisData } from './types';

// why_losing carries an analysis payload covering all three signal viz kinds
// (panelist_mix, split_bar, timeline), quotes, rejection clusters and silver
// medalists — exercising every render branch in one fixture.
const ANALYSIS = CORTEX_INSIGHTS.why_losing.analysis as CortexAnalysisData;
const ARTIFACT_ID = 'ca-test';

function seed(data: CortexAnalysisData) {
  useArtifactStore.getState().openArtifact({
    id: ARTIFACT_ID,
    type: 'cortex-analysis',
    title: data.title,
    initialData: data,
  });
}

beforeEach(() => useArtifactStore.getState().reset());
afterEach(cleanup);

describe('CortexAnalysisArtifact', () => {
  test('renders null when artifact is absent', () => {
    const { container } = render(<CortexAnalysisArtifact id="ca" artifactId="missing" />);
    expect(container.firstChild).toBeNull();
  });

  test('renders the composing skeleton when signals are absent', () => {
    useArtifactStore.getState().openArtifact({
      id: ARTIFACT_ID,
      type: 'cortex-analysis',
      title: 'pending',
      initialData: { title: 'pending' },
    });
    const { container } = render(<CortexAnalysisArtifact id="ca" artifactId={ARTIFACT_ID} />);
    expect(container.querySelector('#ca')?.textContent).toContain('Cortex is composing');
  });

  test('renders hero, takeaway, all signals, quotes, clusters and silver medalists', () => {
    seed(ANALYSIS);
    const { container } = render(<CortexAnalysisArtifact id="ca" artifactId={ARTIFACT_ID} />);

    expect(container.querySelector('#ca-hero')?.textContent).toContain(ANALYSIS.role);
    expect(container.querySelector('#ca-takeaway')?.textContent).toContain(ANALYSIS.takeaway);

    for (const signal of ANALYSIS.signals) {
      const card = container.querySelector(`#ca-signal-${signal.id}`);
      expect(card).not.toBeNull();
      expect(card?.textContent).toContain(signal.title);
      // Each signal renders its viz container.
      expect(container.querySelector(`#ca-signal-${signal.id}-viz`)).not.toBeNull();
    }

    // Quotes section: one figure per quote.
    for (let i = 0; i < ANALYSIS.quotes.length; i += 1) {
      expect(container.querySelector(`#ca-quote-${i}`)).not.toBeNull();
    }

    // Rejection-cluster chart renders.
    expect(container.querySelector('#ca-clusters-chart')).not.toBeNull();

    // One silver-medalist card per candidate.
    for (const candidate of ANALYSIS.silverMedalists) {
      expect(container.querySelector(`#ca-card-${candidate.id}`)).not.toBeNull();
    }
  });

  test('draft-all and per-candidate draft buttons invoke their callbacks', () => {
    seed(ANALYSIS);
    let draftAllCount = 0;
    const drafted: string[] = [];
    const { container } = render(
      <CortexAnalysisArtifact
        id="ca"
        artifactId={ARTIFACT_ID}
        onDraftAll={() => {
          draftAllCount += 1;
        }}
        onDraftNote={(candidateId) => drafted.push(candidateId)}
      />,
    );

    const reengage = container.querySelector('#ca-reengage');
    const draftAllBtn = reengage?.querySelector('button');
    expect(draftAllBtn).not.toBeNull();
    fireEvent.click(draftAllBtn as Element);
    expect(draftAllCount).toBe(1);

    const first = ANALYSIS.silverMedalists[0];
    const cardBtn = container.querySelector(`#ca-card-${first?.id}`)?.querySelector('button');
    expect(cardBtn).not.toBeNull();
    fireEvent.click(cardBtn as Element);
    expect(drafted).toContain(first?.id);
  });

  test('omits draft affordances when no callbacks are supplied', () => {
    seed(ANALYSIS);
    const { container } = render(<CortexAnalysisArtifact id="ca" artifactId={ARTIFACT_ID} />);
    // No "Draft all" button in the re-engage header without onDraftAll.
    expect(container.querySelector('#ca-reengage button')).toBeNull();
  });
});
