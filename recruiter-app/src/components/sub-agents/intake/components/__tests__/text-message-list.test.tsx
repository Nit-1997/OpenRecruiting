import { describe, expect, it } from 'bun:test';
import { fireEvent, render } from '@testing-library/react';
import type { Turn } from '@/types/intake';
import { TextMessageList } from '../text-message-list';

// jsdom does not lay out, so scroll metrics are 0 unless mocked. Pin clientHeight
// and drive scrollHeight from a variable to simulate content growing taller than
// the viewport as new transcript turns land.
function mockScrollMetrics(el: HTMLElement, getScrollHeight: () => number, clientHeight: number) {
  Object.defineProperty(el, 'clientHeight', { configurable: true, value: clientHeight });
  Object.defineProperty(el, 'scrollHeight', { configurable: true, get: getScrollHeight });
}

const turn = (idx: number, role: 'user' | 'assistant', content: string): Turn => ({
  idx,
  role,
  content,
  modality: 'text',
  timestamp: '2026-05-28T10:00:00Z',
});

describe('TextMessageList', () => {
  it('renders empty state when no turns and not streaming', () => {
    render(<TextMessageList turns={[]} streamingAssistantText="" isStreaming={false} />);
    expect(document.getElementById('v2-intake-text-message-list-empty')).not.toBeNull();
  });

  it('renders one bubble per turn with stable ids', () => {
    const { container } = render(
      <TextMessageList
        turns={[turn(0, 'user', 'hi'), turn(1, 'assistant', 'hello there')]}
        streamingAssistantText=""
        isStreaming={false}
      />,
    );
    expect(container.textContent).toContain('hi');
    expect(container.textContent).toContain('hello there');
    expect(document.getElementById('v2-intake-text-message-0')).not.toBeNull();
    expect(document.getElementById('v2-intake-text-message-1')).not.toBeNull();
  });

  it('renders the streaming bubble with the in-progress text', () => {
    render(
      <TextMessageList
        turns={[turn(0, 'user', 'hi')]}
        streamingAssistantText="Hel"
        isStreaming={true}
      />,
    );
    expect(
      document.getElementById('v2-intake-text-message-streaming-content')?.textContent,
    ).toContain('Hel');
  });

  it('list root carries role=log aria-live=polite', () => {
    render(<TextMessageList turns={[]} streamingAssistantText="" isStreaming={false} />);
    const root = document.getElementById('v2-intake-text-message-list');
    expect(root?.getAttribute('role')).toBe('log');
    expect(root?.getAttribute('aria-live')).toBe('polite');
  });

  it('follows the latest turn even when a new turn is taller than the viewport', () => {
    let scrollHeight = 100;
    const { rerender } = render(
      <TextMessageList
        turns={[turn(0, 'assistant', 'hi')]}
        streamingAssistantText=""
        isStreaming={false}
      />,
    );
    const el = document.getElementById('v2-intake-text-message-list') as HTMLDivElement;
    mockScrollMetrics(el, () => scrollHeight, 100);

    // A long voice agent turn lands — content is far taller than the viewport.
    scrollHeight = 600;
    rerender(
      <TextMessageList
        turns={[turn(0, 'assistant', 'hi'), turn(1, 'assistant', 'a'.repeat(800))]}
        streamingAssistantText=""
        isStreaming={false}
      />,
    );

    expect(el.scrollTop).toBe(600);
  });

  it('follows when the last turn grows in place (streamed voice transcript)', () => {
    let scrollHeight = 600;
    const { rerender } = render(
      <TextMessageList
        turns={[turn(0, 'assistant', 'partial')]}
        streamingAssistantText=""
        isStreaming={false}
      />,
    );
    const el = document.getElementById('v2-intake-text-message-list') as HTMLDivElement;
    mockScrollMetrics(el, () => scrollHeight, 100);

    scrollHeight = 1200;
    rerender(
      <TextMessageList
        turns={[turn(0, 'assistant', 'partial answer that keeps growing as OpenRecruiting speaks')]}
        streamingAssistantText=""
        isStreaming={false}
      />,
    );

    expect(el.scrollTop).toBe(1200);
  });

  it('does not yank the recruiter down after they scroll up to re-read', () => {
    let scrollHeight = 600;
    const { rerender } = render(
      <TextMessageList
        turns={[turn(0, 'assistant', 'hi')]}
        streamingAssistantText=""
        isStreaming={false}
      />,
    );
    const el = document.getElementById('v2-intake-text-message-list') as HTMLDivElement;
    mockScrollMetrics(el, () => scrollHeight, 100);

    // Recruiter scrolls up to read earlier context.
    el.scrollTop = 50;
    fireEvent.scroll(el);

    scrollHeight = 900;
    rerender(
      <TextMessageList
        turns={[turn(0, 'assistant', 'hi'), turn(1, 'assistant', 'b'.repeat(800))]}
        streamingAssistantText=""
        isStreaming={false}
      />,
    );

    expect(el.scrollTop).toBe(50);
  });
});
