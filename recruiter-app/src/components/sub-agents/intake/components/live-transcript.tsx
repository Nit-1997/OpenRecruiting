'use client';

import { useEffect, useRef } from 'react';
import type { Turn } from '@/types/intake';

interface Props {
  turns: Turn[];
}

export function LiveTranscript({ turns }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll on every turn count + last-content change
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (nearBottom) {
      el.scrollTop = el.scrollHeight;
    }
  }, [turns.length, turns[turns.length - 1]?.content]);

  const ordered = [...(turns ?? [])].sort((a, b) => (a.idx ?? 0) - (b.idx ?? 0));

  return (
    <div id="v2-intake-convo" data-testid="v2-intake-convo" className="mz-convo">
      <div className="mz-convo-head">
        <span className="mz-eyebrow">Transcript</span>
        <span className="mz-convo-count">{ordered.length} turns</span>
      </div>
      {ordered.length === 0 ? (
        <div
          id="v2-intake-transcript-empty"
          data-testid="v2-intake-transcript-empty"
          className="mz-goal-hint"
        >
          Start the call — OpenRecruiting&apos;s first line and your replies will appear here as you talk.
        </div>
      ) : (
        <div
          id="v2-intake-transcript"
          data-testid="v2-intake-transcript"
          ref={containerRef}
          role="log"
          aria-live="polite"
          aria-relevant="additions text"
          className="mz-convo-scroll"
        >
          {ordered.map((t) => (
            <div
              id={`v2-intake-transcript-turn-${t.idx}`}
              data-testid={`v2-intake-transcript-turn-${t.idx}`}
              key={t.idx}
              className="mz-turn"
            >
              <div
                id={`v2-intake-transcript-speaker-${t.idx}`}
                className="mz-turn-speaker"
                data-role={t.role}
              >
                {t.role === 'user' ? 'You' : 'OpenRecruiting'}
              </div>
              <div id={`v2-intake-transcript-content-${t.idx}`} className="mz-turn-text">
                {t.content}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
