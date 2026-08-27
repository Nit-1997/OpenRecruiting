'use client';

import { Bell, Briefcase, Moon, Plug, Sun } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import { SettingsDrawer, type SettingsTab } from '@/components/settings-drawer/drawer';
import { NotificationsDrawer } from '@/components/settings-drawer/notifications-drawer';
import { cn } from '@/lib/utils';
import { useAuthStore, useShellStore, useThemeStore } from '@/stores';
import type { RailViewId } from '@/types';
import { ProfilePopover } from './profile-popover';

interface RightRailProps {
  id: string;
}

// First + last initial (e.g. "Taylor Marsh" → "NB"), or just the first initial
// when there is no last name (e.g. "Taylor" → "N"). Falls back to the email
// local-part when a display name has not loaded yet.
function avatarInitials(name: string | null, email: string): string {
  const source = name?.trim() || email.split('@')[0] || email || '';
  const parts = source.split(/\s+/).filter(Boolean);
  const first = parts[0]?.[0] ?? '';
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : '';
  return (first + last).toUpperCase() || '?';
}

const RAIL_ITEMS: Array<{ id: RailViewId; label: string; Icon: typeof Briefcase }> = [
  { id: 'roles', label: 'Roles', Icon: Briefcase },
  { id: 'integrations', label: 'Integrations', Icon: Plug },
];

const VALID_SETTINGS_TABS: readonly SettingsTab[] = ['profile', 'team', 'billing'];

export function RightRail({ id }: RightRailProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeRailId = useShellStore((s) => s.activeRailId);
  const authProfile = useAuthStore((s) => s.profile);
  const themeMode = useThemeStore((s) => s.mode);
  const toggleTheme = useThemeStore((s) => s.toggle);
  const applyTheme = useThemeStore((s) => s.apply);
  const isDark = themeMode === 'dark';
  const [profileOpen, setProfileOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState<SettingsTab | null>(null);
  const [notificationsOpen, setNotificationsOpen] = useState(false);

  useEffect(() => {
    applyTheme();
  }, [applyTheme]);

  useEffect(() => {
    const tab = searchParams.get('settings') as SettingsTab | null;
    if (tab && VALID_SETTINGS_TABS.includes(tab)) {
      setSettingsOpen(tab);
    }
  }, [searchParams]);

  useEffect(() => {
    if (!profileOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setProfileOpen(false);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [profileOpen]);

  return (
    <aside
      id={id}
      aria-label="Traditional view rail"
      className="relative flex w-12 shrink-0 flex-col items-center justify-between border-border border-l bg-bg py-3 sm:w-14 sm:py-4"
    >
      <div id={`${id}-primary`} className="flex flex-col items-center gap-1.5">
        {RAIL_ITEMS.map(({ id: viewId, label, Icon }) => {
          const active = activeRailId === viewId;
          return (
            <button
              key={viewId}
              id={`${id}-${viewId}`}
              type="button"
              aria-label={label}
              aria-pressed={active}
              title={label}
              onClick={() => {
                if (active) router.push('/');
                else router.push(`/view/${viewId}`);
              }}
              className={cn(
                'flex h-9 w-9 items-center justify-center rounded-[10px] border transition-colors',
                active
                  ? 'border-transparent bg-text-primary text-white'
                  : 'border-transparent text-text-muted hover:bg-surface hover:text-text-primary',
              )}
            >
              <Icon strokeWidth={1.75} className="h-4 w-4" />
            </button>
          );
        })}
      </div>

      <div id={`${id}-pinned`} className="flex flex-col items-center gap-1.5">
        <button
          id={`${id}-notif`}
          type="button"
          aria-label="Notifications"
          title="Notifications"
          onClick={() => setNotificationsOpen(true)}
          className="flex h-9 w-9 items-center justify-center rounded-[10px] text-text-muted transition-colors hover:bg-surface hover:text-text-primary"
        >
          <Bell strokeWidth={1.75} className="h-4 w-4" />
        </button>
        <button
          id={`${id}-theme`}
          type="button"
          aria-label="Toggle theme"
          aria-pressed={isDark}
          title={isDark ? 'Light mode' : 'Dark mode'}
          onClick={() => toggleTheme()}
          className="flex h-9 w-9 items-center justify-center rounded-[10px] text-text-muted transition-colors hover:bg-surface hover:text-text-primary"
        >
          {isDark ? (
            <Sun strokeWidth={1.75} className="h-4 w-4" />
          ) : (
            <Moon strokeWidth={1.75} className="h-4 w-4" />
          )}
        </button>
        <div id={`${id}-profile-wrap`} className="relative mt-1">
          <button
            id={`${id}-avatar`}
            type="button"
            aria-label={authProfile?.name ? `Profile: ${authProfile.name}` : 'Profile'}
            aria-haspopup="menu"
            aria-expanded={profileOpen}
            onClick={() => setProfileOpen((v) => !v)}
            className="flex h-8 w-8 items-center justify-center rounded-full border border-[#E5E3DF] bg-[#EEE8DD] font-medium text-[#111111] text-[12px]"
          >
            {avatarInitials(authProfile?.name ?? null, authProfile?.email ?? '')}
          </button>
          <ProfilePopover
            id={`${id}-profile-popover`}
            open={profileOpen}
            onClose={() => setProfileOpen(false)}
            onOpenSettings={(tab) => setSettingsOpen(tab)}
          />
        </div>
      </div>

      <SettingsDrawer
        id={`${id}-settings`}
        open={settingsOpen !== null}
        initialTab={settingsOpen ?? 'profile'}
        onClose={() => setSettingsOpen(null)}
      />
      <NotificationsDrawer
        id={`${id}-notifications-drawer`}
        open={notificationsOpen}
        onClose={() => setNotificationsOpen(false)}
      />
    </aside>
  );
}
