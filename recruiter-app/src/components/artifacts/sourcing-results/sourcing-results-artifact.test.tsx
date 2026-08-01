import { afterEach, beforeEach, describe, expect, test } from 'bun:test';
import { cleanup, fireEvent, render } from '@testing-library/react';
import { parseQuery } from '@/fixtures/sourcing-queries';
import { SOURCING_CANDIDATES } from '@/fixtures/sourcing-results';
import { useArtifactStore } from '@/stores';
import {
  SourcingResultsArtifact,
  type SourcingResultsArtifactData,
} from './sourcing-results-artifact';

const ARTIFACT_ID = 'sr-test';
const CRITERIA = parseQuery('Staff PM in San Francisco with 8 years fintech, React, TypeScript');

function mkData(overrides: Partial<SourcingResultsArtifactData> = {}): SourcingResultsArtifactData {
  return {
    criteria: CRITERIA,
    roleLabel: 'Staff PM · Sourcing',
    candidates: SOURCING_CANDIDATES,
    selectedIds: [],
    totalMatchesLabel: '5.3k',
    page: 0,
    pageSize: 3,
    ...overrides,
  };
}

function seed(data: SourcingResultsArtifactData, isBuilding = false) {
  useArtifactStore.getState().openArtifact({
    id: ARTIFACT_ID,
    type: 'sourcing-results',
    title: 'Sourcing',
    initialData: data,
  });
  if (!isBuilding) useArtifactStore.getState().completeArtifact(ARTIFACT_ID);
}

beforeEach(() => useArtifactStore.getState().reset());
afterEach(cleanup);

describe('SourcingResultsArtifact', () => {
  test('renders null when the artifact is absent', () => {
    const { container } = render(<SourcingResultsArtifact id="sr" artifactId="missing" />);
    expect(container.firstChild).toBeNull();
  });

  test('renders role label, filter pills, and a paginated list of candidate cards', () => {
    seed(mkData());
    const { container } = render(<SourcingResultsArtifact id="sr" artifactId={ARTIFACT_ID} />);

    expect(container.querySelector('#sr-role-label-text')?.textContent).toContain('Staff PM');
    expect(container.querySelector('#sr-filters')).not.toBeNull();

    // pageSize=3 → first three (by match score) candidates render as cards.
    const cards = container.querySelectorAll('#sr-list > li');
    expect(cards.length).toBe(3);

    // Pager reflects multiple pages.
    expect(container.querySelector('#sr-pager-stat')?.textContent).toContain('Page 1 of');
  });

  test('shows the empty state when no candidates match', () => {
    seed(mkData({ candidates: [] }));
    const { container } = render(<SourcingResultsArtifact id="sr" artifactId={ARTIFACT_ID} />);
    expect(container.querySelector('#sr-list-empty')?.textContent).toContain('No candidates match');
  });

  test('toggling a candidate and changing page invoke their callbacks', () => {
    seed(mkData());
    const toggled: string[] = [];
    let pageChange = -1;
    const { container } = render(
      <SourcingResultsArtifact
        id="sr"
        artifactId={ARTIFACT_ID}
        onToggleCandidate={(cid) => toggled.push(cid)}
        onPageChange={(p) => {
          pageChange = p;
        }}
      />,
    );

    const firstCheck = container.querySelector('#sr-list input[type="checkbox"]');
    expect(firstCheck).not.toBeNull();
    fireEvent.click(firstCheck as Element);
    expect(toggled.length).toBe(1);

    fireEvent.click(container.querySelector('#sr-pager-next') as Element);
    expect(pageChange).toBe(1);
  });

  test('sort control re-orders to years of experience', () => {
    seed(mkData());
    const { container } = render(<SourcingResultsArtifact id="sr" artifactId={ARTIFACT_ID} />);
    const sort = container.querySelector('#sr-sort') as HTMLSelectElement;
    expect(sort).not.toBeNull();
    fireEvent.change(sort, { target: { value: 'yoe' } });
    // After re-sort the list still renders one page worth of cards.
    expect(container.querySelectorAll('#sr-list > li').length).toBe(3);
  });

  test('actions footer enables add-to-pipeline when candidates are selected', () => {
    const firstId = SOURCING_CANDIDATES[0]?.id ?? '';
    seed(mkData({ selectedIds: [firstId] }));
    let added = 0;
    const { container } = render(
      <SourcingResultsArtifact
        id="sr"
        artifactId={ARTIFACT_ID}
        onAddSelectedToPipeline={() => {
          added += 1;
        }}
      />,
    );
    const addBtn = container.querySelector('#sr-actions-add') as HTMLButtonElement;
    expect(addBtn).not.toBeNull();
    expect(addBtn.disabled).toBe(false);
    fireEvent.click(addBtn);
    expect(added).toBe(1);
  });
});
