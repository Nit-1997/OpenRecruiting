import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'bun:test';
import { Label } from './label';

describe('Label', () => {
  test('renders with mono-label utilities + muted text', () => {
    render(<Label id="l">DAILY BRIEF</Label>);
    const el = screen.getByText('DAILY BRIEF');
    expect(el.className).toContain('font-mono-label');
    expect(el.className).toContain('text-text-muted');
  });

  test('dot prop renders colored leading circle', () => {
    render(<Label id="l" dot="#10b981">LIVE</Label>);
    const el = screen.getByText('LIVE').parentElement;
    expect(el?.querySelector('[data-label-dot]')).toBeTruthy();
  });

  test('accent variant swaps to pill form', () => {
    render(<Label id="l" variant="accent">Active</Label>);
    const el = screen.getByText('Active');
    expect(el.className).toContain('bg-surface');
    expect(el.className).toContain('rounded-full');
    expect(el.className).toContain('text-charcoal');
  });

  test('renders a <label> element', () => {
    render(<Label id="l">EMAIL</Label>);
    const el = screen.getByText('EMAIL');
    expect(el.tagName).toBe('LABEL');
  });

  test('associates with a control via htmlFor (querying by label finds the input)', () => {
    render(
      <div>
        <Label id="email-label" htmlFor="email-input">
          Email
        </Label>
        <input id="email-input" type="email" />
      </div>,
    );
    const control = screen.getByLabelText('Email');
    expect(control.tagName).toBe('INPUT');
    expect(control.id).toBe('email-input');
  });

  test('accent variant still renders a <label> with htmlFor', () => {
    render(
      <Label id="l" variant="accent" htmlFor="ctrl">
        Active
      </Label>,
    );
    const el = screen.getByText('Active');
    expect(el.tagName).toBe('LABEL');
    expect(el.getAttribute('for')).toBe('ctrl');
  });
});
