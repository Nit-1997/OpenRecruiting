import { describe, expect, test } from 'bun:test';
import { fireEvent, render } from '@testing-library/react';
import { GuidelineRow } from './guideline-row';

function defined<T>(x: T | null | undefined): T {
  if (x === null || x === undefined) throw new Error('expected defined');
  return x;
}

describe('GuidelineRow', () => {
  test('renders title + description', () => {
    const { container } = render(
      <GuidelineRow
        id="gl"
        index={0}
        guideline={{ title: 'Probe', description: 'Ask why, twice.' }}
        onSave={() => {}}
        onDelete={() => {}}
      />,
    );
    expect(defined(container.querySelector('#gl-0-title')).textContent).toBe('Probe');
    expect(defined(container.querySelector('#gl-0-description')).textContent).toBe(
      'Ask why, twice.',
    );
  });

  test('save fires onSave with patched guideline', () => {
    const received: Array<{ title: string; description: string }> = [];
    const { container } = render(
      <GuidelineRow
        id="gl"
        index={0}
        guideline={{ title: 'A', description: 'B' }}
        onSave={(p) => received.push(p)}
        onDelete={() => {}}
      />,
    );
    fireEvent.click(defined(container.querySelector('#gl-0-edit')));
    const input = defined(container.querySelector('#gl-0-title-input')) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'X' } });
    fireEvent.click(defined(container.querySelector('#gl-0-save')));
    expect(received).toEqual([{ title: 'X', description: 'B' }]);
  });

  test('delete fires onDelete with index', () => {
    const received: number[] = [];
    const { container } = render(
      <GuidelineRow
        id="gl"
        index={2}
        guideline={{ title: 'A', description: 'B' }}
        onSave={() => {}}
        onDelete={(i) => received.push(i)}
      />,
    );
    fireEvent.click(defined(container.querySelector('#gl-2-delete')));
    expect(received).toEqual([2]);
  });
});
