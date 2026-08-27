import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'bun:test';
import { Avatar } from './avatar';

describe('Avatar', () => {
  test('renders initials from single-word name', () => {
    render(<Avatar id="a" name="Taylor" />);
    expect(screen.getByText('TA')).toBeTruthy();
  });

  test('renders initials from multi-word name', () => {
    render(<Avatar id="a" name="Sarah Chen" />);
    expect(screen.getByText('SC')).toBeTruthy();
  });

  test('color is deterministic from name hash', () => {
    const { container, rerender } = render(<Avatar id="a" name="Ada" />);
    const firstClass = container.firstChild?.textContent ? container.innerHTML : '';
    rerender(<Avatar id="a" name="Ada" />);
    const secondClass = container.innerHTML;
    expect(firstClass).toBe(secondClass);
  });

  test('size classes', () => {
    render(<Avatar id="a" name="N" size="lg" />);
    const el = screen.getByText('NN').parentElement;
    expect(el?.className).toContain('size-10');
  });
});
