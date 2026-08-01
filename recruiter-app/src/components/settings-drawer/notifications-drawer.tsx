'use client';

import { X } from 'lucide-react';
import { useEffect } from 'react';
import { NotificationsTab } from './notifications-tab';

interface NotificationsDrawerProps {
  id: string;
  open: boolean;
  onClose: () => void;
}

export function NotificationsDrawer({ id, open, onClose }: NotificationsDrawerProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div id={id} className="fixed inset-0 z-40 flex justify-end bg-black/30" role="presentation">
      <button
        id={`${id}-backdrop`}
        type="button"
        aria-label="Close notifications"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-transparent"
      />
      <aside
        id={`${id}-panel`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        className="relative flex h-full w-full max-w-[640px] flex-col overflow-hidden border-border border-l bg-white shadow-[0_0_80px_rgba(0,0,0,0.2)]"
      >
        <header className="flex items-start justify-between gap-4 border-border border-b px-4 py-3 sm:px-6 sm:py-4">
          <div>
            <p className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
              Preferences
            </p>
            <h2
              id={`${id}-title`}
              className="mt-1 font-display text-[22px] text-text-primary leading-tight"
            >
              Notifications
            </h2>
          </div>
          <button
            id={`${id}-close`}
            type="button"
            aria-label="Close notifications"
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-full text-text-muted hover:bg-surface hover:text-text-primary"
          >
            <X strokeWidth={1.75} className="h-4 w-4" />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-6 sm:py-5">
          <NotificationsTab id={`${id}-content`} />
        </div>
      </aside>
    </div>
  );
}
