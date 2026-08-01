import { describe, expect, test } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import { AtsSourceBadge } from './ats-source-badge';

describe('AtsSourceBadge', () => {
  test('renders capitalized provider for ats_sync rows', () => {
    render(<AtsSourceBadge id="b1" source="ats_sync" provider="workable" />);
    expect(screen.getByText('Workable')).toBeTruthy();
    cleanup();
  });

  test('falls back to generic ATS label without provider', () => {
    render(<AtsSourceBadge id="b2" source="ats_sync" provider={null} />);
    expect(screen.getByText('ATS')).toBeTruthy();
    cleanup();
  });

  test('renders nothing for native rows', () => {
    const { container } = render(<AtsSourceBadge id="b3" source="openrecruiting" provider="workable" />);
    expect(container.innerHTML).toBe('');
    cleanup();
  });

  test('renders nothing when source missing', () => {
    const { container } = render(<AtsSourceBadge id="b4" />);
    expect(container.innerHTML).toBe('');
    cleanup();
  });
});
