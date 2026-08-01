'use client';

import { Brain as BrainIcon, Sparkles, X } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

export interface WorkspaceTabDescriptor {
  id: string;
  label: string;
  /** Pinned tabs can't be closed (e.g. the brain graph). */
  pinned?: boolean;
  /** Soft hint for which icon to show. */
  kind?: 'brain' | 'analysis';
}

interface WorkspaceTabsProps {
  id: string;
  tabs: WorkspaceTabDescriptor[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onClose?: (id: string) => void;
}

function iconFor(kind: WorkspaceTabDescriptor['kind']): ReactNode {
  if (kind === 'analysis') return <Sparkles strokeWidth={1.75} className="h-3.5 w-3.5" />;
  return <BrainIcon strokeWidth={1.75} className="h-3.5 w-3.5" />;
}

export function WorkspaceTabs({ id, tabs, activeId, onSelect, onClose }: WorkspaceTabsProps) {
  if (tabs.length === 0) return null;
  return (
    <div
      id={id}
      role="tablist"
      aria-label="Workspace tabs"
      className="pointer-events-auto inline-flex max-w-full items-center gap-1 overflow-x-auto rounded-full border border-border bg-white/95 p-1 shadow-sm backdrop-blur"
    >
      {tabs.map((t) => {
        const active = t.id === activeId;
        return (
          <div
            key={t.id}
            className={cn(
              'group inline-flex items-center gap-1 rounded-full transition-colors',
              active ? 'bg-text-primary text-white' : 'text-text-muted hover:bg-surface',
            )}
          >
            <button
              id={`${id}-tab-${t.id}`}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => onSelect(t.id)}
              className={cn(
                'inline-flex max-w-[220px] items-center gap-1.5 rounded-full px-3 py-1 font-medium font-sans text-[12px]',
                active ? 'text-white' : 'hover:text-text-primary',
                !t.pinned && onClose ? 'pr-1' : '',
              )}
            >
              <span aria-hidden className={active ? 'text-white' : 'text-text-muted'}>
                {iconFor(t.kind)}
              </span>
              <span className="truncate">{t.label}</span>
              {t.pinned && (
                <span
                  className={cn(
                    'ml-0.5 shrink-0 rounded-full px-1.5 font-mono text-[9px] uppercase tracking-[0.14em]',
                    active ? 'bg-white/20 text-white/90' : 'bg-surface text-text-faint',
                  )}
                >
                  default
                </span>
              )}
            </button>
            {!t.pinned && onClose && (
              <button
                type="button"
                onClick={() => onClose(t.id)}
                aria-label={`Close ${t.label}`}
                className={cn(
                  'mr-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full transition-colors',
                  active
                    ? 'text-white/70 hover:bg-white/15 hover:text-white'
                    : 'text-text-faint hover:bg-surface hover:text-text-primary',
                )}
              >
                <X strokeWidth={2} className="h-3 w-3" />
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
