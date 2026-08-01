import { describe, expect, test } from 'bun:test';
import { render } from '@testing-library/react';
import type { RoundCategory } from '@/types';
import { RoundCategoryBadge } from './round-category-badge';

describe('RoundCategoryBadge', () => {
  const cases: Array<[RoundCategory, string]> = [
    ['screening', 'Screening'],
    ['coding', 'Coding'],
    ['design', 'Design'],
    ['behavioral', 'Behavioral'],
    ['domain', 'Domain'],
    ['culture', 'Culture'],
    ['panel', 'Panel'],
    ['assessment', 'Assessment'],
  ];

  for (const [category, label] of cases) {
    test(`renders ${category} → "${label}"`, () => {
      const { container } = render(<RoundCategoryBadge id="rcb" category={category} />);
      const el = container.querySelector('#rcb');
      expect(el?.textContent).toBe(label);
      expect(el?.getAttribute('data-category')).toBe(category);
    });
  }

  test('applies mono uppercase styling classes', () => {
    const { container } = render(<RoundCategoryBadge id="rcb" category="coding" />);
    const el = container.querySelector('#rcb');
    const cls = el?.className ?? '';
    expect(cls).toContain('font-mono');
    expect(cls).toContain('uppercase');
  });
});
