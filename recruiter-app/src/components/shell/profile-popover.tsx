'use client';

import { CreditCard, LogOut, User, Users } from 'lucide-react';
import { useRef } from 'react';
import type { SettingsTab } from '@/components/settings-drawer/drawer';
import { useFocusTrap } from '@/hooks/use-focus-trap';
import { useAuthStore } from '@/stores';
import { getRuntimeConfig } from '@/lib/runtime-config';

interface ProfilePopoverProps {
  id: string;
  open: boolean;
  onClose: () => void;
  onOpenSettings?: (tab: SettingsTab) => void;
}

interface MenuEntry {
  tab: SettingsTab;
  label: string;
  Icon: typeof User;
}

const ENTRIES: MenuEntry[] = [
  { tab: 'profile', label: 'Profile', Icon: User },
  { tab: 'team', label: 'Team', Icon: Users },
  { tab: 'billing', label: 'Billing & plan', Icon: CreditCard },
];

export function ProfilePopover({ id, open, onClose, onOpenSettings }: ProfilePopoverProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const signOut = useAuthStore((s) => s.signOut);
  useFocusTrap(rootRef, open, onClose);
  if (!open) return null;
  return (
    <div
      id={id}
      ref={rootRef}
      role="menu"
      aria-label="Profile menu"
      className="absolute right-full bottom-0 z-40 mr-3 w-[240px] rounded-xl border border-border bg-white shadow-[0_8px_32px_rgba(0,0,0,0.08)]"
    >
      {ENTRIES.map(({ tab, label, Icon }) => (
        <button
          key={tab}
          id={`${id}-${tab}`}
          type="button"
          role="menuitem"
          onClick={() => {
            onClose();
            onOpenSettings?.(tab);
          }}
          className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm text-text-primary transition-colors hover:bg-surface"
        >
          <Icon strokeWidth={1.75} className="h-4 w-4" />
          {label}
        </button>
      ))}
      <div className="border-border/60 border-t" />
      <button
        id={`${id}-logout`}
        type="button"
        role="menuitem"
        onClick={() => {
          onClose();
          signOut();
          window.location.href = `${getRuntimeConfig().landingUrl || 'http://localhost:3000'}/login`;
        }}
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm text-status-danger-fg transition-colors hover:bg-status-danger-bg"
      >
        <LogOut strokeWidth={1.75} className="h-4 w-4" />
        Log out
      </button>
    </div>
  );
}
