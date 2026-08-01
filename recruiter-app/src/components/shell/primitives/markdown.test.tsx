/**
 * Tests for the chat-bubble markdown renderer. The LLM emits GFM-ish markdown
 * (bold, lists, pipe tables, headings, rules) — every block must land as a
 * real element, not raw pipe/asterisk soup (the regression that motivated it).
 */

import { afterEach, describe, expect, test } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import { renderMarkdown } from './markdown';

afterEach(() => cleanup());

function renderText(text: string) {
  return render(<div data-testid="md-root">{renderMarkdown(text)}</div>);
}

describe('renderMarkdown', () => {
  test('plain single paragraph renders inline (no block wrapper)', () => {
    renderText('Just a sentence.');
    const root = screen.getByTestId('md-root');
    expect(root.textContent).toBe('Just a sentence.');
    expect(root.querySelector('p')).toBeNull();
  });

  test('non-string children pass through unchanged', () => {
    const node = <span data-testid="raw">raw</span>;
    render(<div>{renderMarkdown(node)}</div>);
    expect(screen.getByTestId('raw').textContent).toBe('raw');
  });

  test('bold, italic and inline code render as elements', () => {
    renderText('A **bold** and *soft* `code` mix.');
    const root = screen.getByTestId('md-root');
    expect(root.querySelector('strong')?.textContent).toBe('bold');
    expect(root.querySelector('em')?.textContent).toBe('soft');
    expect(root.querySelector('code')?.textContent).toBe('code');
  });

  test('single newlines inside a paragraph become line breaks', () => {
    renderText('line one\nline two');
    expect(screen.getByTestId('md-root').querySelector('br')).not.toBeNull();
  });

  test('dash bullets render as a list', () => {
    renderText('Here:\n- first **point**\n- second');
    const root = screen.getByTestId('md-root');
    const items = root.querySelectorAll('ul li');
    expect(items).toHaveLength(2);
    expect(items[0]?.querySelector('strong')?.textContent).toBe('point');
  });

  test('numbered items render as an ordered list', () => {
    renderText('1. Which candidate?\n2. Which round?');
    const items = screen.getByTestId('md-root').querySelectorAll('ol li');
    expect(items).toHaveLength(2);
    expect(items[1]?.textContent).toBe('Which round?');
  });

  test('pipe table with separator renders header and body cells', () => {
    renderText('| Round | Rating |\n|---|---|\n| AI Depth | **Strong Yes** |\n| Panel | Yes |');
    const root = screen.getByTestId('md-root');
    const headers = root.querySelectorAll('th');
    expect(headers).toHaveLength(2);
    expect(headers[0]?.textContent).toBe('Round');
    const cells = root.querySelectorAll('td');
    expect(cells).toHaveLength(4);
    expect(cells[1]?.querySelector('strong')?.textContent).toBe('Strong Yes');
    // No raw pipe characters survive into the rendered text.
    expect(root.textContent).not.toContain('|');
    expect(root.textContent).not.toContain('---');
  });

  test('pipe rows without a separator still render as a table', () => {
    renderText('| a | b |\n| c | d |');
    const root = screen.getByTestId('md-root');
    expect(root.querySelectorAll('th')).toHaveLength(0);
    expect(root.querySelectorAll('td')).toHaveLength(4);
  });

  test('ragged table rows are padded to the widest row', () => {
    renderText('| a | b | c |\n|---|---|---|\n| only |');
    const root = screen.getByTestId('md-root');
    expect(root.querySelectorAll('tbody td')).toHaveLength(3);
  });

  test('headings render as semibold lines, not document headings', () => {
    renderText('## Where is the friction?\n\nIn leadership.');
    const root = screen.getByTestId('md-root');
    expect(root.querySelector('h1, h2, h3')).toBeNull();
    expect(root.textContent).toContain('Where is the friction?');
    expect(root.textContent).not.toContain('##');
  });

  test('horizontal rules render as a divider, not literal dashes', () => {
    renderText('above\n\n---\n\nbelow');
    const root = screen.getByTestId('md-root');
    expect(root.textContent).not.toContain('---');
    expect(root.textContent).toContain('above');
    expect(root.textContent).toContain('below');
  });

  test('mixed message (prose + table + bullets) keeps every block', () => {
    const text =
      'Her scored rounds:\n\n| Round | Rating |\n|---|---|\n| AI Depth | Strong Yes |\n\n**Friction:**\n- rated Maybe yet the summary reads positive\n- worth challenging';
    renderText(text);
    const root = screen.getByTestId('md-root');
    expect(root.querySelectorAll('table')).toHaveLength(1);
    expect(root.querySelectorAll('ul li')).toHaveLength(2);
    expect(root.textContent).toContain('Her scored rounds:');
  });
});
