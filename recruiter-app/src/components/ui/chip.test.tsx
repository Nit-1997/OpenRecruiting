import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'bun:test';
import { Chip } from './chip';

describe('Chip', () => {
  test('status variant renders with optional dot', () => {
    render(<Chip id="c" variant="status" dotColor="#10b981">Active</Chip>);
    const el = screen.getByText('Active').parentElement;
    expect(el?.querySelector('[data-chip-dot]')).toBeTruthy();
  });

  test('action variant is clickable + outlined', () => {
    const handler = () => undefined;
    render(<Chip id="c" variant="action" onClick={handler}>Add</Chip>);
    const el = screen.getByRole('button', { name: 'Add' });
    expect(el.className).toContain('border');
    expect(el.className).toContain('cursor-pointer');
  });

  test('assumption variant has green leading check', () => {
    render(<Chip id="c" variant="assumption">Title: Sr PM</Chip>);
    const el = screen.getByText(/Title: Sr PM/);
    expect(el.parentElement?.querySelector('[data-chip-check]')).toBeTruthy();
  });
});
