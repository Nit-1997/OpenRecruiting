'use client';

import { ArrowLeft, Maximize2, Minimize2, MoreHorizontal, Share2, X } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface ArtifactHeadProps {
  id: string;
  primaryAction?: { label: string; onClick: () => void; icon?: ReactNode };
  expanded: boolean;
  onToggleExpand: () => void;
  onShare?: () => void;
  onClose: () => void;
  onBack?: () => void;
}

export function ArtifactHead({
  id,
  primaryAction,
  expanded,
  onToggleExpand,
  onShare,
  onClose,
  onBack,
}: ArtifactHeadProps) {
  return (
    <div
      id={id}
      className="pointer-events-auto inline-flex items-center gap-1 rounded-full border border-border bg-white/95 px-1.5 py-1 shadow-sm backdrop-blur"
    >
      {onBack && (
        <button
          id={`${id}-back`}
          type="button"
          aria-label="Back to previous artifact"
          onClick={onBack}
          className="flex h-7 w-7 items-center justify-center rounded-full text-text-muted transition-colors hover:bg-surface hover:text-text-primary"
        >
          <ArrowLeft strokeWidth={1.75} className="h-3.5 w-3.5" />
        </button>
      )}
      {primaryAction && (
        <button
          id={`${id}-primary`}
          type="button"
          onClick={primaryAction.onClick}
          className={cn(
            'mx-1 inline-flex h-7 items-center gap-1.5 rounded-full px-3 font-medium text-[12.5px] transition-colors',
            'bg-text-primary text-white hover:bg-[#222]',
          )}
        >
          {primaryAction.icon}
          <span>{primaryAction.label}</span>
        </button>
      )}
      <button
        id={`${id}-more`}
        type="button"
        aria-label="More actions"
        className="flex h-7 w-7 items-center justify-center rounded-full text-text-muted transition-colors hover:bg-surface hover:text-text-primary"
      >
        <MoreHorizontal strokeWidth={1.75} className="h-3.5 w-3.5" />
      </button>
      {onShare && (
        <button
          id={`${id}-share`}
          type="button"
          aria-label="Share artifact"
          onClick={onShare}
          className="flex h-7 w-7 items-center justify-center rounded-full text-text-muted transition-colors hover:bg-surface hover:text-text-primary"
        >
          <Share2 strokeWidth={1.75} className="h-3.5 w-3.5" />
        </button>
      )}
      <button
        id={`${id}-expand`}
        type="button"
        aria-label={expanded ? 'Collapse artifact' : 'Expand artifact'}
        onClick={onToggleExpand}
        className="flex h-7 w-7 items-center justify-center rounded-full text-text-muted transition-colors hover:bg-surface hover:text-text-primary"
      >
        {expanded ? (
          <Minimize2 strokeWidth={1.75} className="h-3.5 w-3.5" />
        ) : (
          <Maximize2 strokeWidth={1.75} className="h-3.5 w-3.5" />
        )}
      </button>
      <button
        id={`${id}-close`}
        type="button"
        aria-label="Close artifact"
        onClick={onClose}
        className="flex h-7 w-7 items-center justify-center rounded-full text-text-muted transition-colors hover:bg-surface hover:text-text-primary"
      >
        <X strokeWidth={1.75} className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
