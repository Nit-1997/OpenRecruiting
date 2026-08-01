import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'bun:test';
import { Phone } from 'lucide-react';
import { IconButton } from './icon-button';

describe('IconButton', () => {
  test('renders circular button with icon child', () => {
    render(<IconButton id="ib" aria-label="Call"><Phone /></IconButton>);
    const el = screen.getByRole('button', { name: 'Call' });
    expect(el.className).toContain('rounded-full');
    expect(el.querySelector('svg')).toBeTruthy();
  });

  test('md size is 32x32', () => {
    render(<IconButton id="ib" aria-label="A"><Phone /></IconButton>);
    const el = screen.getByRole('button');
    expect(el.className).toContain('size-8');
  });

  test('primary variant has charcoal bg', () => {
    render(<IconButton id="ib" aria-label="A" variant="primary"><Phone /></IconButton>);
    const el = screen.getByRole('button');
    expect(el.className).toContain('bg-charcoal');
    expect(el.className).toContain('text-white');
  });

  test('ghost is default', () => {
    render(<IconButton id="ib" aria-label="A"><Phone /></IconButton>);
    const el = screen.getByRole('button');
    expect(el.className).toContain('text-text-secondary');
  });
});
