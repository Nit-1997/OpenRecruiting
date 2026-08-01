import { afterEach, describe, expect, test } from 'bun:test';
import { cleanup, render } from '@testing-library/react';
import { RoleSummary } from './role-summary';

afterEach(cleanup);

describe('RoleSummary', () => {
  test('renders **Key:** value lines as labeled rows', () => {
    const markdown = ['**Role:** Staff Product Manager', '**Location:** Sunnyvale, CA'].join('\n');
    const { container } = render(<RoleSummary id="rs" markdown={markdown} />);

    const row0 = container.querySelector('#rs-row-0');
    expect(row0?.textContent).toContain('Role');
    expect(row0?.textContent).toContain('Staff Product Manager');

    const row1 = container.querySelector('#rs-row-1');
    expect(row1?.textContent).toContain('Location');
    expect(row1?.textContent).toContain('Sunnyvale, CA');
  });

  test('renders non-key lines as plain paragraphs', () => {
    const { container } = render(
      <RoleSummary id="rs" markdown={'This is a freeform summary line.'} />,
    );
    expect(container.querySelector('#rs-line-0')?.textContent).toBe(
      'This is a freeform summary line.',
    );
  });

  test('skips blank lines and renders a mix of rows and paragraphs', () => {
    const markdown = ['**Role:** PM', '', 'Standalone note', '**Seniority:** Staff'].join('\n');
    const { container } = render(<RoleSummary id="rs" markdown={markdown} />);
    // Blank line dropped → indices are 0:Role row, 1:paragraph, 2:Seniority row.
    expect(container.querySelector('#rs-row-0')?.textContent).toContain('Role');
    expect(container.querySelector('#rs-line-1')?.textContent).toBe('Standalone note');
    expect(container.querySelector('#rs-row-2')?.textContent).toContain('Seniority');
  });

  test('renders an empty container for empty markdown', () => {
    const { container } = render(<RoleSummary id="rs" markdown="" />);
    const root = container.querySelector('#rs');
    expect(root).not.toBeNull();
    expect(root?.children.length).toBe(0);
  });
});
