import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'bun:test';
import { Search } from 'lucide-react';
import { Input } from './input';

describe('Input', () => {
  test('bordered default renders border + rounded-input + bg-tile', () => {
    render(<Input id="i" placeholder="Type…" />);
    const el = screen.getByPlaceholderText('Type…');
    expect(el.className).toContain('border');
    expect(el.className).toContain('border-border');
    expect(el.className).toContain('rounded-input');
    expect(el.className).toContain('bg-tile');
  });

  test('ghost variant has no border', () => {
    render(<Input id="i" placeholder="x" variant="ghost" />);
    const el = screen.getByPlaceholderText('x');
    expect(el.className).toContain('border-0');
  });

  test('mono prop applies font-mono', () => {
    render(<Input id="i" placeholder="15" mono />);
    const el = screen.getByPlaceholderText('15');
    expect(el.className).toContain('font-mono');
  });

  test('leading icon renders next to input', () => {
    render(<Input id="i" placeholder="q" leadingIcon={<Search data-testid="lead" />} />);
    expect(screen.getByTestId('lead')).toBeTruthy();
  });
});
