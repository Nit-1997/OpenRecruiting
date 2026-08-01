import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'bun:test';
import { Card } from './card';

describe('Card', () => {
  test('renders with default tile bg + border + shadow', () => {
    render(<Card id="c">hello</Card>);
    const el = screen.getByText('hello').parentElement;
    expect(el?.className).toContain('bg-tile');
    expect(el?.className).toContain('border');
    expect(el?.className).toContain('border-border');
    expect(el?.className).toContain('shadow-card');
    expect(el?.className).toContain('rounded-card-lg');
  });

  test('hoverable adds border-strong on hover', () => {
    render(<Card id="c" hoverable>hi</Card>);
    const el = screen.getByText('hi').parentElement;
    expect(el?.className).toContain('hover:border-border-strong');
  });

  test('interactive adds cursor-pointer + focus ring', () => {
    render(<Card id="c" interactive onClick={() => undefined}>click</Card>);
    const el = screen.getByText('click').parentElement;
    expect(el?.className).toContain('cursor-pointer');
    expect(el?.className).toContain('focus-visible:ring-2');
  });
});
