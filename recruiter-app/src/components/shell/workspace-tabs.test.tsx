import { afterEach, describe, expect, test } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { type WorkspaceTabDescriptor, WorkspaceTabs } from './workspace-tabs';

afterEach(cleanup);

const TABS: WorkspaceTabDescriptor[] = [
  { id: 'brain', label: 'Brain', pinned: true, kind: 'brain' },
  { id: 'analysis-1', label: 'Cortex analysis', kind: 'analysis' },
  { id: 'analysis-2', label: 'Sourcing strategy', kind: 'analysis' },
];

describe('WorkspaceTabs', () => {
  test('renders nothing when tabs is empty', () => {
    const { container } = render(
      <WorkspaceTabs id="w" tabs={[]} activeId={null} onSelect={() => {}} />,
    );
    // The hook returns null for empty input — container has no child elements
    expect(container.firstChild).toBeNull();
  });

  test('renders one tab per descriptor with the right labels', () => {
    render(<WorkspaceTabs id="w" tabs={TABS} activeId="brain" onSelect={() => {}} />);
    expect(screen.getByText('Brain')).toBeDefined();
    expect(screen.getByText('Cortex analysis')).toBeDefined();
    expect(screen.getByText('Sourcing strategy')).toBeDefined();
  });

  test('marks the active tab with aria-selected', () => {
    render(<WorkspaceTabs id="w" tabs={TABS} activeId="analysis-1" onSelect={() => {}} />);
    const active = screen.getByText('Cortex analysis').closest('[role="tab"]');
    expect(active?.getAttribute('aria-selected')).toBe('true');
  });

  test('calls onSelect with the clicked tab id', () => {
    let picked = '';
    render(
      <WorkspaceTabs
        id="w"
        tabs={TABS}
        activeId="brain"
        onSelect={(id) => {
          picked = id;
        }}
      />,
    );
    fireEvent.click(screen.getByText('Cortex analysis'));
    expect(picked).toBe('analysis-1');
  });

  test('renders close affordance on non-pinned tabs only', () => {
    render(
      <WorkspaceTabs id="w" tabs={TABS} activeId="brain" onSelect={() => {}} onClose={() => {}} />,
    );
    // Pinned tab has no Close button rendered anywhere.
    expect(screen.queryByLabelText('Close Brain')).toBeNull();
    // Non-pinned tabs have one.
    expect(screen.getByLabelText('Close Cortex analysis')).toBeDefined();
    expect(screen.getByLabelText('Close Sourcing strategy')).toBeDefined();
  });

  test('clicking close fires onClose with the tab id (and does not also fire onSelect)', () => {
    let closed = '';
    let selected = '';
    render(
      <WorkspaceTabs
        id="w"
        tabs={TABS}
        activeId="brain"
        onSelect={(id) => {
          selected = id;
        }}
        onClose={(id) => {
          closed = id;
        }}
      />,
    );
    fireEvent.click(screen.getByLabelText('Close Cortex analysis'));
    expect(closed).toBe('analysis-1');
    expect(selected).toBe('');
  });
});
