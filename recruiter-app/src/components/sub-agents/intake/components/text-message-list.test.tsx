import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, render } from '@testing-library/react';
import type { Turn } from '@/types/intake';
import { TextMessageList } from './text-message-list';

afterEach(cleanup);

function turn(idx: number, role: 'user' | 'assistant', content: string): Turn {
  return { idx, role, content, modality: 'text', timestamp: '2026-05-30T00:00:00Z' };
}

describe('TextMessageList', () => {
  it('renders the optimistic pending user bubble when pendingUserText is set', () => {
    const { getByText } = render(
      <TextMessageList
        turns={[]}
        streamingAssistantText=""
        isStreaming={false}
        pendingUserText="my optimistic message"
        noAnimIdxs={[]}
      />,
    );
    expect(getByText('my optimistic message')).toBeDefined();
  });

  it('marks a recently-committed turn with data-no-anim so it does not re-animate', () => {
    const { container } = render(
      <TextMessageList
        turns={[turn(1, 'assistant', 'final reply')]}
        streamingAssistantText=""
        isStreaming={false}
        pendingUserText={null}
        noAnimIdxs={[1]}
      />,
    );
    const node = container.querySelector('#v2-intake-text-message-1');
    expect(node?.getAttribute('data-no-anim')).toBe('true');
  });

  it('does not mark unrelated turns as no-anim', () => {
    const { container } = render(
      <TextMessageList
        turns={[turn(2, 'assistant', 'other')]}
        streamingAssistantText=""
        isStreaming={false}
        pendingUserText={null}
        noAnimIdxs={[1]}
      />,
    );
    const node = container.querySelector('#v2-intake-text-message-2');
    expect(node?.getAttribute('data-no-anim')).toBe(null);
  });
});
