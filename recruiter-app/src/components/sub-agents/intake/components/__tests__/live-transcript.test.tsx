import { describe, expect, it } from 'bun:test';
import { render, screen } from '@testing-library/react';
import { LiveTranscript } from '@/components/sub-agents/intake/components/live-transcript';
import type { Turn } from '@/types/intake';

const turns: Turn[] = [
  {
    idx: 0,
    role: 'assistant',
    content: 'Hey, OpenRecruiting here.',
    modality: 'voice',
    timestamp: '2026-05-28T00:00:00Z',
  },
  { idx: 1, role: 'user', content: 'Hi.', modality: 'voice', timestamp: '2026-05-28T00:00:05Z' },
  {
    idx: 2,
    role: 'assistant',
    content: 'Tell me about the role.',
    modality: 'voice',
    timestamp: '2026-05-28T00:00:08Z',
  },
];

describe('LiveTranscript', () => {
  it('renders an empty hint when turns are empty', () => {
    render(<LiveTranscript turns={[]} />);
    expect(document.getElementById('v2-intake-transcript-empty')).not.toBeNull();
  });

  it('renders one row per turn in idx order', () => {
    render(<LiveTranscript turns={[...turns].reverse()} />);
    const rows = screen.getAllByTestId(/^v2-intake-transcript-turn-/);
    expect(rows.length).toBe(3);
    expect(rows[0]?.getAttribute('id')).toBe('v2-intake-transcript-turn-0');
    expect(rows[2]?.getAttribute('id')).toBe('v2-intake-transcript-turn-2');
  });

  it('container has role=log + aria-live=polite for accessibility', () => {
    render(<LiveTranscript turns={turns} />);
    const log = document.getElementById('v2-intake-transcript');
    expect(log).not.toBeNull();
    expect(log?.getAttribute('role')).toBe('log');
    expect(log?.getAttribute('aria-live')).toBe('polite');
  });

  it('shows speaker label per role', () => {
    const { container } = render(<LiveTranscript turns={turns} />);
    expect(container.textContent).toContain('OpenRecruiting');
    expect(container.textContent).toContain('You');
  });
});
