import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'bun:test';
import { Plus } from 'lucide-react';
import { Button, type ButtonProps } from './button';

describe('Button', () => {
  test('primary md renders charcoal bg + pill shape with contrast-correct foreground', () => {
    render(<Button id="btn">Hello</Button>);
    const el = screen.getByRole('button', { name: 'Hello' });
    expect(el.className).toContain('bg-charcoal');
    expect(el.className).toContain('rounded-full');
    // --canvas flips OPPOSITE to --charcoal in dark mode, so text-canvas
    // contrasts on the charcoal fill in BOTH themes (text-white does not).
    expect(el.className).toContain('text-canvas');
    expect(el.className).not.toContain('text-white');
  });

  test('secondary variant is outlined', () => {
    render(<Button id="btn" variant="secondary">Secondary</Button>);
    const el = screen.getByRole('button');
    expect(el.className).toContain('border');
    expect(el.className).toContain('border-border-strong');
    expect(el.className).not.toContain('bg-charcoal');
  });

  test('ghost variant is text-only', () => {
    render(<Button id="btn" variant="ghost">Ghost</Button>);
    const el = screen.getByRole('button');
    expect(el.className).not.toContain('bg-charcoal');
    expect(el.className).not.toContain('border-border-strong');
  });

  test('size variants adjust height', () => {
    const { rerender } = render(<Button id="btn" size="sm">A</Button>);
    expect(screen.getByRole('button').className).toContain('h-7');
    rerender(<Button id="btn" size="lg">A</Button>);
    expect(screen.getByRole('button').className).toContain('h-11');
  });

  test('renders leading icon when provided', () => {
    render(
      <Button id="btn" icon={<Plus data-testid="leading-icon" />}>Add</Button>,
    );
    expect(screen.getByTestId('leading-icon')).toBeTruthy();
  });

  test('applies focus-visible ring utilities', () => {
    render(<Button id="btn">A</Button>);
    const el = screen.getByRole('button');
    expect(el.className).toContain('focus-visible:ring-2');
    expect(el.className).toContain('focus-visible:ring-black/15');
  });

  test('dead asChild prop is removed from the public type', () => {
    // The previous Button accepted `asChild` and silently discarded it (a
    // no-op). It has been removed from ButtonProps entirely — there is no
    // `asChild` key on the prop type, so consumers can no longer pass it.
    type HasAsChild = 'asChild' extends keyof ButtonProps ? true : false;
    const propAbsent: HasAsChild = false;
    expect(propAbsent).toBe(false);

    // And the rendered output is always a plain <button> (no alternate
    // element / Slot composition path).
    render(<Button id="btn">Click</Button>);
    expect(screen.getByRole('button', { name: 'Click' }).tagName).toBe('BUTTON');
  });
});
