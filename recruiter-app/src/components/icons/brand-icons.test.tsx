import { afterEach, describe, expect, test } from 'bun:test';
import { cleanup, render } from '@testing-library/react';
import {
  AshbyIcon,
  ClaudeIcon,
  GreenhouseIcon,
  LeverIcon,
  AgentIcon,
  BrandIcon,
  SlackIcon,
} from './brand-icons';

afterEach(cleanup);

describe('brand icons — render smoke tests', () => {
  test('BrandIcon renders an SVG and forwards className', () => {
    render(<BrandIcon className="h-6 w-6" data-testid="mz" />);
    const svg = document.querySelector('[data-testid="mz"]');
    expect(svg).not.toBeNull();
    expect(svg?.tagName.toLowerCase()).toBe('svg');
    expect(svg?.getAttribute('class')).toContain('h-6');
  });

  test('AgentIcon renders without crashing', () => {
    const { container } = render(<AgentIcon className="h-4 w-4" />);
    expect(container.querySelector('svg')).not.toBeNull();
  });

  // Brand image components render an <img> (logo bitmaps). All take id +
  // className.
  test.each([
    ['SlackIcon', SlackIcon],
    ['AshbyIcon', AshbyIcon],
    ['GreenhouseIcon', GreenhouseIcon],
    ['LeverIcon', LeverIcon],
    ['ClaudeIcon', ClaudeIcon],
  ])('%s renders with the provided id', (_name, Component) => {
    render(<Component id={`icon-${_name}`} className="h-5 w-5" />);
    const el = document.getElementById(`icon-${_name}`);
    expect(el).not.toBeNull();
  });
});
