'use client';

import { Gauge, User, Users, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';
import { BillingTab } from './billing-tab';
import { ProfileTab } from './profile-tab';
import { TeamTab } from './team-tab';

export type SettingsTab = 'profile' | 'team' | 'billing';

interface SettingsDrawerProps {
  id: string;
  open: boolean;
  initialTab?: SettingsTab;
  onClose: () => void;
}

const TABS: Array<{ key: SettingsTab; label: string; Icon: typeof User }> = [
  { key: 'profile', label: 'Profile', Icon: User },
  { key: 'team', label: 'Team', Icon: Users },
  // Key stays 'billing': it is the ?settings= value and the /billing route
  // shim's target. Only the label changed — there is no payment surface here,
  // so a card icon and the word "Billing" both oversold it.
  { key: 'billing', label: 'Credit budget', Icon: Gauge },
];

export function SettingsDrawer({ id, open, initialTab = 'profile', onClose }: SettingsDrawerProps) {
  const [tab, setTab] = useState<SettingsTab>(initialTab);

  useEffect(() => {
    if (open) setTab(initialTab);
  }, [open, initialTab]);

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
        type="button"
        aria-label="Close settings"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-transparent"
      />
      <aside
        id={`${id}-panel`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        className="relative flex h-full w-full max-w-[960px] flex-col overflow-hidden border-border border-l bg-white shadow-[0_0_80px_rgba(0,0,0,0.2)]"
      >
        <header className="flex items-start justify-between gap-4 border-border border-b px-4 py-3 sm:px-6 sm:py-4">
          <h2
            id={`${id}-title`}
            className="font-display text-[22px] text-text-primary leading-tight"
          >
            Settings
          </h2>
          <button
            type="button"
            aria-label="Close settings"
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-full text-text-muted hover:bg-surface hover:text-text-primary"
          >
            <X strokeWidth={1.75} className="h-4 w-4" />
          </button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col md:flex-row">
          <nav
            id={`${id}-nav`}
            aria-label="Settings tabs"
            className="shrink-0 overflow-x-auto border-border border-b bg-surface/40 px-2 py-2 md:w-[220px] md:border-r md:border-b-0 md:px-3 md:py-4"
          >
            <ul className="flex flex-row gap-1 md:flex-col">
              {TABS.map(({ key, label, Icon }) => {
                const active = tab === key;
                return (
                  <li key={key}>
                    <button
                      id={`${id}-tab-${key}`}
                      type="button"
                      onClick={() => setTab(key)}
                      className={cn(
                        'flex w-full shrink-0 items-center gap-2 whitespace-nowrap rounded-[10px] border px-3 py-2 text-left text-[13px] transition-colors',
                        active
                          ? 'border-text-primary bg-white text-text-primary'
                          : 'border-transparent text-text-muted hover:border-border hover:bg-white hover:text-text-primary',
                      )}
                    >
                      <Icon strokeWidth={1.75} className="h-4 w-4" />
                      {label}
                    </button>
                  </li>
                );
              })}
            </ul>
          </nav>

          <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-6 sm:py-5">
            {tab === 'profile' && <ProfileTab id={`${id}-profile`} />}
            {tab === 'team' && <TeamTab id={`${id}-team`} />}
            {tab === 'billing' && <BillingTab id={`${id}-billing`} />}
          </div>
        </div>
      </aside>
    </div>
  );
}
