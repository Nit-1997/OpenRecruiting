'use client';

import { useEffect, useRef } from 'react';
import { AgentMark } from '@/components/sub-agents/intake/primitives';
import type { Turn } from '@/types/intake';

interface Props {
  turns: Turn[];
  streamingAssistantText: string;
  isStreaming: boolean;
  /** Optimistic, not-yet-persisted user message to show after `turns`. */
  pendingUserText?: string | null;
  /** Turn idxs that just committed from a stream — render without entry animation. */
  noAnimIdxs?: number[];
}

const NEAR_BOTTOM_PX = 64;

// Assistant messages carry the OpenRecruiting mark avatar (design: ConvThread); user
// messages are a bare right-aligned bubble. Bubbles are text-only — coverage
// status lives in the checklist, not the transcript.
function AgentAvatar() {
  return (
    <div className="mz-msg-avatar">
      <AgentMark size={14} />
    </div>
  );
}

export function TextMessageList({
  turns,
  streamingAssistantText,
  isStreaming,
  pendingUserText = null,
  noAnimIdxs = [],
}: Props) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // Follow new turns until the recruiter scrolls up to re-read; resume once they
  // return to the bottom. The intent is captured from real scroll events
  // (pre-mutation) — never re-derived from the scroll position *after* a turn is
  // appended, since a single tall voice turn would otherwise read as "scrolled up"
  // and freeze the transcript.
  const stickToBottomRef = useRef(true);
  const noAnim = new Set(noAnimIdxs);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX;
  };

  // Re-runs on a new turn AND on the last turn growing in place (voice transcript
  // streamed into one turn) — both must keep the latest message in view.
  const lastTurnContent = turns.at(-1)?.content;

  // biome-ignore lint/correctness/useExhaustiveDependencies: deps are intentional re-scroll triggers, not values read in the body
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (stickToBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [turns.length, lastTurnContent, streamingAssistantText, isStreaming, pendingUserText]);

  return (
    <div
      id="v2-intake-text-message-list"
      ref={scrollRef}
      onScroll={handleScroll}
      className="mz-convo-scroll"
      role="log"
      aria-live="polite"
    >
      {turns.length === 0 && !isStreaming && !pendingUserText && (
        <div
          id="v2-intake-text-message-list-empty"
          data-testid="v2-intake-text-message-list-empty"
          className="mz-msg-bubble"
          style={{ color: 'var(--text-muted)', fontStyle: 'italic', background: 'transparent' }}
        >
          Say hi to start. The agent already has draft answers from your form and past roles &mdash;
          it&apos;ll validate, probe where vague, and ask fresh where it has nothing.
        </div>
      )}

      {turns.map((turn) => {
        const isUser = turn.role === 'user';
        return (
          <div
            id={`v2-intake-text-message-${turn.idx}`}
            key={turn.idx}
            className={isUser ? 'mz-msg-user' : 'mz-msg-agent'}
            {...(noAnim.has(turn.idx) ? { 'data-no-anim': 'true' } : {})}
            style={noAnim.has(turn.idx) ? { animation: 'none' } : undefined}
          >
            {!isUser && <AgentAvatar />}
            <div
              id={`v2-intake-text-message-bubble-${turn.idx}`}
              className="mz-msg-bubble whitespace-pre-wrap"
              data-role={turn.role}
            >
              <span id={`v2-intake-text-message-content-${turn.idx}`}>{turn.content}</span>
            </div>
          </div>
        );
      })}

      {pendingUserText && (
        <div id="v2-intake-text-message-pending" className="mz-msg-user" data-pending="true">
          <div
            id="v2-intake-text-message-pending-bubble"
            className="mz-msg-bubble whitespace-pre-wrap"
            data-role="user"
          >
            {pendingUserText}
          </div>
        </div>
      )}

      {isStreaming && (
        <div
          id="v2-intake-text-message-streaming"
          className="mz-msg-agent"
          style={{ animation: 'none' }}
        >
          <AgentAvatar />
          <div
            id="v2-intake-text-message-streaming-bubble"
            className="mz-msg-bubble whitespace-pre-wrap"
            data-role="assistant"
          >
            <span
              id="v2-intake-text-message-streaming-content"
              data-testid="v2-intake-text-message-streaming-content"
            >
              {streamingAssistantText}
            </span>
            <span id="v2-intake-text-message-streaming-cursor" className="animate-pulse">
              |
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
