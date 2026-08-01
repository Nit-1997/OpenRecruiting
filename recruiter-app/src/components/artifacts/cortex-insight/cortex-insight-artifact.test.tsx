import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { cleanup, render } from '@testing-library/react';
import { CORTEX_INSIGHTS } from '@/fixtures/cortex-insights';
import { useArtifactStore } from '@/stores';
import { CortexInsightArtifact } from './cortex-insight-artifact';
import type { CortexInsightArtifactData } from './types';

const FIXTURE = CORTEX_INSIGHTS.why_losing;
const ARTIFACT_ID = 'ci-test';

function seed(data: CortexInsightArtifactData) {
  useArtifactStore.getState().openArtifact({
    id: ARTIFACT_ID,
    type: 'cortex-insight',
    title: data.title,
    initialData: data,
  });
}

function completeData(): CortexInsightArtifactData {
  return {
    title: FIXTURE.title,
    elapsedLabel: FIXTURE.elapsedLabel,
    steps: FIXTURE.steps,
    activeStepNum: null,
    stats: FIXTURE.stats,
    complete: true,
  };
}

beforeEach(() => useArtifactStore.getState().reset());
afterEach(cleanup);

describe('CortexInsightArtifact', () => {
  test('renders null when artifact is absent', () => {
    const { container } = render(<CortexInsightArtifact id="ci" artifactId="missing" />);
    expect(container.firstChild).toBeNull();
  });

  test('renders the thinking skeleton when steps are absent', () => {
    useArtifactStore.getState().openArtifact({
      id: ARTIFACT_ID,
      type: 'cortex-insight',
      title: 'pending',
      initialData: { title: 'pending' },
    });
    const { container } = render(<CortexInsightArtifact id="ci" artifactId={ARTIFACT_ID} />);
    expect(container.querySelector('#ci')?.textContent).toContain('Cortex is thinking');
  });

  test('renders the full completed trail with all steps, stats and the done marker', () => {
    seed(completeData());
    const { container } = render(<CortexInsightArtifact id="ci" artifactId={ARTIFACT_ID} />);

    // Title + elapsed label from the fixture.
    expect(container.querySelector('#ci')?.textContent).toContain(FIXTURE.title);
    expect(container.querySelector('#ci-trail')?.textContent).toContain(FIXTURE.elapsedLabel);

    // When complete, every step is visible.
    for (const step of FIXTURE.steps) {
      const el = container.querySelector(`#ci-step-${step.num}`);
      expect(el).not.toBeNull();
      expect(el?.textContent).toContain(step.body);
    }

    // Completion marker present.
    expect(container.querySelector('#ci-step-complete')?.textContent).toContain('Response ready');

    // One stat section per stat card, with its rows. (ids contain spaces, so
    // assert against the rendered text rather than a CSS id selector.)
    const root = container.querySelector('#ci');
    for (const card of FIXTURE.stats) {
      expect(root?.textContent).toContain(card.title);
      expect(root?.textContent).toContain(card.rows[0]?.label ?? '');
    }
  });

  test('streaming render only shows steps up to the active step (no completion marker)', () => {
    const active = FIXTURE.steps[2];
    seed({
      title: FIXTURE.title,
      elapsedLabel: FIXTURE.elapsedLabel,
      steps: FIXTURE.steps,
      activeStepNum: active?.num ?? null,
      stats: [],
      complete: false,
    });
    const { container } = render(<CortexInsightArtifact id="ci" artifactId={ARTIFACT_ID} />);

    // The active step and earlier steps render; later steps are hidden.
    expect(container.querySelector(`#ci-step-${active?.num}`)).not.toBeNull();
    const later = FIXTURE.steps[5];
    expect(container.querySelector(`#ci-step-${later?.num}`)).toBeNull();
    expect(container.querySelector('#ci-step-complete')).toBeNull();
  });
});
