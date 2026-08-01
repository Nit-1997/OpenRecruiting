import { render } from '@testing-library/react';
import { describe, expect, test } from 'bun:test';
import { AgentMark } from './agent-mark';

describe('AgentMark', () => {
  test('renders svg with openrecruiting fill', () => {
    const { container } = render(<AgentMark id="m" size="md" />);
    const svg = container.querySelector('svg');
    expect(svg).toBeTruthy();
    const filled = svg?.querySelector('[data-agent-fill]');
    expect(filled?.getAttribute('fill')).toContain('--color-accent-agent');
  });

  test('sizes apply height/width', () => {
    const { container } = render(<AgentMark id="m" size="sm" />);
    const svg = container.querySelector('svg');
    expect(svg?.getAttribute('width')).toBe('16');
    expect(svg?.getAttribute('height')).toBe('16');
  });
});
