'use client';

import type { KeyboardEvent, ReactNode } from 'react';
import { useCallback, useEffect, useRef } from 'react';
import { useArtifactStore, useSessionStore, useShellStore, useSplitStore } from '@/stores';
import { ArtifactColumn } from './artifact-column';
import { ChatColumn } from './chat-column';

interface SplitShellProps {
  id: string;
  children: ReactNode;
}

const STEP = 0.02;

export function SplitShell({ id, children }: SplitShellProps) {
  const ratio = useSplitStore((s) => s.ratio);
  const setRatio = useSplitStore((s) => s.setRatio);
  const draggingRef = useRef(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const activeTabId = useShellStore((s) => s.activeTabId);
  const session = useSessionStore((s) => (activeTabId ? s.sessions[activeTabId] : null));
  const artifactId = session?.artifactId ?? null;
  const hasArtifact = useArtifactStore((s) =>
    artifactId ? Boolean(s.artifacts[artifactId]) : false,
  );

  const onMouseMove = useCallback(
    (e: MouseEvent) => {
      if (!draggingRef.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const next = (e.clientX - rect.left) / rect.width;
      setRatio(next);
    },
    [setRatio],
  );

  const onMouseUp = useCallback(() => {
    if (!draggingRef.current) return;
    draggingRef.current = false;
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  }, []);

  useEffect(() => {
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, [onMouseMove, onMouseUp]);

  const onMouseDown = () => {
    draggingRef.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowLeft') {
      e.preventDefault();
      setRatio(ratio - STEP);
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      setRatio(ratio + STEP);
    }
  };

  const chatPct = Math.round(ratio * 100);
  const artPct = 100 - chatPct;
  const gridTemplateColumns = hasArtifact ? `${chatPct}% 6px ${artPct}%` : '1fr 0 0';

  return (
    <div
      id={id}
      ref={containerRef}
      className="flex min-h-0 flex-1 flex-col md:grid"
      style={{
        gridTemplateColumns,
        transition: 'grid-template-columns 280ms ease-out',
      }}
    >
      <ChatColumn id={`${id}-chat`}>{children}</ChatColumn>
      {hasArtifact && (
        <>
          {/* biome-ignore lint/a11y/useSemanticElements: draggable/focusable splitter handle is not an <hr> */}
          <div
            id={`${id}-divider`}
            role="separator"
            aria-orientation="vertical"
            aria-valuenow={chatPct}
            aria-valuemin={32}
            aria-valuemax={72}
            tabIndex={0}
            onKeyDown={onKeyDown}
            onMouseDown={onMouseDown}
            className="relative hidden cursor-col-resize bg-border/60 transition-colors hover:bg-text-muted focus:bg-text-muted focus:outline-none md:block"
          />
          <ArtifactColumn id={`${id}-artifact`} />
        </>
      )}
    </div>
  );
}
