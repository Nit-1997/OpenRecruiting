import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { cleanup, fireEvent, render } from '@testing-library/react';
import {
  SOURCING_STRATEGY_CANDIDATES,
  SOURCING_STRATEGY_CHANNELS,
  SOURCING_STRATEGY_DEFAULTS,
  SOURCING_STRATEGY_TOTAL_LABEL,
} from '@/fixtures/sourcing-strategy';
import { useArtifactStore } from '@/stores';
import { SourcingStrategyArtifact } from './sourcing-strategy-artifact';
import type { SourcingStrategyArtifactData, SourcingStrategyPhase } from './types';

const ARTIFACT_ID = 'ss-test';

// Mirror the production assembly in sub-agents/sourcing/flow.ts::baseStrategyData
// so the fixture exercises the real render branches.
function mkData(
  phase: SourcingStrategyPhase,
  overrides: Partial<SourcingStrategyArtifactData> = {},
): SourcingStrategyArtifactData {
  const showingCandidates = phase === 'awaiting_selection' || phase === 'added';
  return {
    strategyId: 'ss_test',
    version: 1,
    roleId: 'role-1',
    roleTitle: 'Staff Product Manager',
    ownerName: 'Nitin',
    createdAtLabel: 'Apr 19 · 10:30 AM',
    ...SOURCING_STRATEGY_DEFAULTS,
    userPreferences: 'Prefer YC-backed AI startups.',
    trailSteps: [],
    trailVisible: false,
    channels: SOURCING_STRATEGY_CHANNELS.map((c) => ({ ...c })),
    candidates: showingCandidates ? SOURCING_STRATEGY_CANDIDATES.map((c) => ({ ...c })) : [],
    selectedCandidateIds: [],
    phase,
    activeTab: 'strategy',
    addedCount: phase === 'added' ? SOURCING_STRATEGY_CANDIDATES.length : 0,
    totalProfilesLabel: SOURCING_STRATEGY_TOTAL_LABEL,
    savedToRole: false,
    shareUrl: null,
    ...overrides,
  };
}

function seed(data: SourcingStrategyArtifactData) {
  useArtifactStore.getState().openArtifact({
    id: ARTIFACT_ID,
    type: 'sourcing-strategy',
    title: 'Sourcing strategy',
    initialData: data,
  });
}

beforeEach(() => useArtifactStore.getState().reset());
afterEach(cleanup);

describe('SourcingStrategyArtifact', () => {
  test('renders null when the artifact is absent', () => {
    const { container } = render(<SourcingStrategyArtifact id="ss" artifactId="missing" />);
    expect(container.firstChild).toBeNull();
  });

  test('renders the drafting skeleton when the ICP is absent', () => {
    useArtifactStore.getState().openArtifact({
      id: ARTIFACT_ID,
      type: 'sourcing-strategy',
      title: 'pending',
      initialData: { phase: 'drafting' },
    });
    const { container } = render(<SourcingStrategyArtifact id="ss" artifactId={ARTIFACT_ID} />);
    expect(container.querySelector('#ss')?.textContent).toContain('Drafting sourcing strategy');
  });

  test('strategy tab renders the ICP brief and tabs toolbar', () => {
    seed(mkData('awaiting_selection'));
    const { container } = render(<SourcingStrategyArtifact id="ss" artifactId={ARTIFACT_ID} />);

    expect(container.querySelector('#ss-tabs')).not.toBeNull();
    expect(container.querySelector('#ss-strategy')).not.toBeNull();
    // ICP summary text from the defaults.
    expect(container.querySelector('#ss-strategy')?.textContent).toContain('Staff Product Manager');
    // Strategy grid renders the calibration cards (must-haves etc.).
    expect(container.querySelector('#ss-strategy-grid')).not.toBeNull();
  });

  test('switching to the candidates tab via the parent callback renders candidate cards', () => {
    // The tab is parent-controlled (data.activeTab). Seed it directly on the
    // candidates tab to exercise that render branch.
    seed(mkData('awaiting_selection', { activeTab: 'candidates' }));
    const { container } = render(<SourcingStrategyArtifact id="ss" artifactId={ARTIFACT_ID} />);

    expect(container.querySelector('#ss-candidates-tab')).not.toBeNull();
    for (const c of SOURCING_STRATEGY_CANDIDATES) {
      expect(container.querySelector(`#ss-candidates-tab-cand-${c.id}`)).not.toBeNull();
    }
    // Channels strip rendered too.
    for (const ch of SOURCING_STRATEGY_CHANNELS) {
      expect(container.querySelector(`#ss-candidates-tab-channel-${ch.id}`)).not.toBeNull();
    }
  });

  test('tab buttons and share/download invoke their callbacks', () => {
    seed(mkData('awaiting_selection'));
    let switched: string | null = null;
    let downloaded = 0;
    let shared = 0;
    const { container } = render(
      <SourcingStrategyArtifact
        id="ss"
        artifactId={ARTIFACT_ID}
        onSwitchTab={(tab) => {
          switched = tab;
        }}
        onDownloadStrategy={() => {
          downloaded += 1;
        }}
        onShareStrategy={() => {
          shared += 1;
        }}
      />,
    );

    fireEvent.click(container.querySelector('#ss-tab-candidates') as Element);
    expect(switched).toBe('candidates');

    fireEvent.click(container.querySelector('#ss-download') as Element);
    expect(downloaded).toBe(1);

    fireEvent.click(container.querySelector('#ss-share') as Element);
    expect(shared).toBe(1);
    // Share button flips to the "Link copied" affordance.
    expect(container.querySelector('#ss-share')?.textContent).toContain('Link copied');
  });

  test('candidate selection and add-to-pipeline fire callbacks in awaiting_selection', () => {
    const first = SOURCING_STRATEGY_CANDIDATES[0];
    seed(
      mkData('awaiting_selection', {
        activeTab: 'candidates',
        selectedCandidateIds: first ? [first.id] : [],
      }),
    );
    const toggled: string[] = [];
    let added = 0;
    const { container } = render(
      <SourcingStrategyArtifact
        id="ss"
        artifactId={ARTIFACT_ID}
        onToggleCandidate={(cid) => toggled.push(cid)}
        onAddSelectedToPipeline={() => {
          added += 1;
        }}
      />,
    );

    const addBtn = container.querySelector('#ss-candidates-tab-add-selected') as HTMLButtonElement;
    expect(addBtn).not.toBeNull();
    expect(addBtn.disabled).toBe(false);
    fireEvent.click(addBtn);
    expect(added).toBe(1);

    // The first card is selectable via its checkbox; toggling fires onToggle.
    const card = container.querySelector(`#ss-candidates-tab-cand-${first?.id}`);
    const checkbox = card?.querySelector('input[type="checkbox"]');
    expect(checkbox).not.toBeNull();
    fireEvent.click(checkbox as Element);
    expect(toggled).toContain(first?.id);

    // The expand button on the card toggles its detail body without crashing.
    const expandBtn = card?.querySelector('button');
    if (expandBtn) fireEvent.click(expandBtn);
  });

  test('added phase shows the back-to-role affordance', () => {
    seed(mkData('added', { activeTab: 'candidates' }));
    let backCount = 0;
    const { container } = render(
      <SourcingStrategyArtifact
        id="ss"
        artifactId={ARTIFACT_ID}
        onBackToRole={() => {
          backCount += 1;
        }}
      />,
    );
    const backBtn = container.querySelector('#ss-candidates-tab-back-to-role');
    expect(backBtn).not.toBeNull();
    fireEvent.click(backBtn as Element);
    expect(backCount).toBe(1);
  });
});
