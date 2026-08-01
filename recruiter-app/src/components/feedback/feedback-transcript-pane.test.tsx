import { afterEach, describe, expect, test } from 'bun:test';
import { cleanup, render } from '@testing-library/react';
import { FeedbackTranscriptPane } from './feedback-transcript-pane';

afterEach(cleanup);

describe('FeedbackTranscriptPane', () => {
  test('renders nothing when closed', () => {
    const { container } = render(
      <FeedbackTranscriptPane open={false} turns={[]} interim="" onClose={() => {}} />,
    );
    expect(container.querySelector('#feedback-transcript-pane')).toBeNull();
  });

  test('renders turns with You/Scout labels + a11y log region', () => {
    const { container } = render(
      <FeedbackTranscriptPane
        open
        turns={[
          { role: 'user', text: 'How did they do?' },
          { role: 'bot', text: 'Strong on system design.' },
        ]}
        interim=""
        onClose={() => {}}
      />,
    );
    const scroll = container.querySelector('#feedback-transcript-pane-scroll');
    expect(scroll?.getAttribute('role')).toBe('log');
    expect(scroll?.getAttribute('aria-live')).toBe('polite');
    expect(container.querySelector('#feedback-transcript-pane-turn-0')?.textContent).toContain(
      'You',
    );
    expect(container.querySelector('#feedback-transcript-pane-turn-1')?.textContent).toContain(
      'OpenRecruiting',
    );
    expect(container.querySelector('#feedback-transcript-pane-turn-1')?.textContent).toContain(
      'Strong on system design.',
    );
  });

  test('renders the live interim row (cleaned)', () => {
    const { container } = render(
      <FeedbackTranscriptPane open turns={[]} interim="Let me think [END]" onClose={() => {}} />,
    );
    const interim = container.querySelector('#feedback-transcript-pane-interim');
    expect(interim?.textContent).toContain('Let me think');
    expect(interim?.textContent).not.toContain('[END]');
  });

  test('shows empty state when no turns and no interim', () => {
    const { container } = render(
      <FeedbackTranscriptPane open turns={[]} interim="" onClose={() => {}} />,
    );
    expect(container.querySelector('#feedback-transcript-pane-empty')).not.toBeNull();
  });
});
