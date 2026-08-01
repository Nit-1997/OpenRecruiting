import { describe, expect, it } from 'bun:test';
import { render } from '@testing-library/react';
import { RoundCategoryBadge } from './round-category-badge';

describe('RoundCategoryBadge', () => {
  it('renders the category label', () => {
    const { getByText } = render(<RoundCategoryBadge category="coding" />);
    expect(getByText('Coding')).toBeTruthy();
  });

  it('applies category-specific class hooks', () => {
    const { container } = render(<RoundCategoryBadge category="design" />);
    expect(container.querySelector('[data-category="design"]')).toBeTruthy();
  });
});
