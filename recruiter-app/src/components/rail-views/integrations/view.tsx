'use client';

import { Check, ChevronDown, Copy, Plug, Settings } from 'lucide-react';
import type { ComponentType } from 'react';
import { useEffect, useState } from 'react';
import { ClaudeIcon, GoogleCalendarIcon, SlackIcon } from '@/components/icons/brand-icons';
import { Skeleton } from '@/components/shell/primitives/skeleton';
import { useToast } from '@/components/ui/toast';
import { COMMON_TIMEZONES, INTEGRATIONS, WORKSPACE_PREFERENCES } from '@/fixtures/integrations';
import { useShellSync } from '@/hooks/use-shell-sync';
import { cn } from '@/lib/utils';
import type { GcalStatus } from '@/services/integrations-gcal';
import {
  disconnectGcal,
  getGcalInstallUrl,
  getGcalStatus,
  toggleAutoJoin,
  toggleCalendarWatch,
} from '@/services/integrations-gcal';
import type { SlackStatus } from '@/services/integrations-slack';
import { disconnectSlack, getSlackInstallUrl, getSlackStatus } from '@/services/integrations-slack';
import { AtsCard } from './ats-card';
import { formatRelativeTime } from './relative-time';

type BrandIconComponent = ComponentType<{ className?: string; id?: string }>;

interface IntegrationsViewProps {
  id: string;
}

export function IntegrationsView({ id }: IntegrationsViewProps) {
  useShellSync();
  const { showToast } = useToast();

  const [slackSettingsOpen, setSlackSettingsOpen] = useState(false);
  const [slackStatus, setSlackStatus] = useState<SlackStatus | null>(null);
  const [slackLoading, setSlackLoading] = useState(true);

  const [gcalSettingsOpen, setGcalSettingsOpen] = useState(false);
  const [claudeEndpointCopied, setClaudeEndpointCopied] = useState(false);

  // GCal real state
  const [gcalStatus, setGcalStatus] = useState<GcalStatus | null>(null);
  const [gcalLoading, setGcalLoading] = useState(true);

  // GCal settings state — initialised from API once loaded
  const [timezone, setTimezone] = useState<string>(WORKSPACE_PREFERENCES.timezone);
  const [autoJoin, setAutoJoin] = useState<boolean>(false);
  const [calendarWatch, setCalendarWatch] = useState<boolean>(true);

  // Load real status on mount and handle OAuth callback params
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const gcalParam = params.get('google_calendar');
    const slackParam = params.get('slack');

    if (gcalParam || slackParam) {
      const url = new URL(window.location.href);
      url.searchParams.delete('google_calendar');
      url.searchParams.delete('slack');
      url.searchParams.delete('reason');
      window.history.replaceState({}, '', url.toString());

      if (gcalParam === 'error') {
        const reason = params.get('reason') ?? 'unknown';
        showToast(`Google Calendar connection failed: ${reason}`, 'error');
      }
      if (slackParam === 'error') {
        const reason = params.get('reason') ?? 'unknown';
        showToast(`Slack connection failed: ${reason}`, 'error');
      }
    }

    getGcalStatus()
      .then((s) => {
        setGcalStatus(s);
        if (s.connected) {
          setCalendarWatch(s.calendar_watch_enabled);
          setAutoJoin(s.auto_join_untracked);
        }
      })
      .catch(() =>
        setGcalStatus({
          connected: false,
          email: null,
          connected_at: null,
          calendar_watch_enabled: true,
          auto_join_untracked: false,
        }),
      )
      .finally(() => setGcalLoading(false));

    getSlackStatus()
      .then((s) => setSlackStatus(s))
      .catch(() =>
        setSlackStatus({
          connected: false,
          team_name: null,
          connected_at: null,
          healthy: null,
          needs_reauth: null,
          auth_state: null,
          token_expires_at: null,
          last_auth_error_code: null,
        }),
      )
      .finally(() => setSlackLoading(false));
  }, []);

  async function handleSlackConnect() {
    try {
      const url = await getSlackInstallUrl();
      window.location.href = url;
    } catch {
      showToast('Failed to start Slack connection. Please try again.', 'error');
    }
  }

  async function handleSlackDisconnect() {
    try {
      await disconnectSlack();
      setSlackStatus((prev) => (prev ? { ...prev, connected: false, team_name: null } : prev));
      setSlackSettingsOpen(false);
    } catch {
      showToast('Failed to disconnect Slack. Please try again.', 'error');
    }
  }

  async function handleGcalConnect() {
    try {
      const url = await getGcalInstallUrl();
      window.location.href = url;
    } catch {
      showToast('Failed to start Google Calendar connection. Please try again.', 'error');
    }
  }

  async function handleGcalDisconnect() {
    try {
      await disconnectGcal();
      setGcalStatus((prev) => (prev ? { ...prev, connected: false, email: null } : prev));
      setGcalSettingsOpen(false);
    } catch {
      showToast('Failed to disconnect Google Calendar. Please try again.', 'error');
    }
  }

  async function handleCalendarWatchChange(v: boolean) {
    setCalendarWatch(v);
    try {
      await toggleCalendarWatch(v);
    } catch {
      setCalendarWatch(!v); // revert on failure
    }
  }

  async function handleAutoJoinChange(v: boolean) {
    setAutoJoin(v);
    try {
      await toggleAutoJoin(v);
    } catch {
      setAutoJoin(!v); // revert on failure
    }
  }

  const gcalConnected = !gcalLoading && gcalStatus?.connected === true;

  return (
    <div id={id} className="pt-6 pb-6 sm:pt-10">
      <header id={`${id}-header`} className="mb-8">
        <h1
          id={`${id}-title`}
          className="font-display font-normal text-[28px] text-text-primary leading-[1.1] tracking-[-0.01em]"
        >
          Integrations
        </h1>
        <p id={`${id}-sub`} className="mt-1.5 text-[14px] text-text-muted leading-[1.55]">
          Connect OpenRecruiting to the tools your team lives in.
        </p>
      </header>

      <section
        id={`${id}-connected`}
        aria-label="Connected integrations"
        className="mb-8 flex flex-col gap-3"
      >
        <div
          id={`${id}-connected-eyebrow`}
          className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.18em]"
        >
          Connected
        </div>

        <SlackCard
          id={`${id}-slack`}
          loading={slackLoading}
          connected={!slackLoading && slackStatus?.connected === true}
          teamName={slackStatus?.team_name ?? null}
          connectedAt={slackStatus?.connected_at ?? null}
          needsReauth={slackStatus?.needs_reauth ?? false}
          settingsOpen={slackSettingsOpen}
          onToggleSettings={() => setSlackSettingsOpen((v) => !v)}
          onConnect={handleSlackConnect}
          onDisconnect={handleSlackDisconnect}
        />

        <GcalCard
          id={`${id}-gcal`}
          loading={gcalLoading}
          connected={gcalConnected}
          email={gcalStatus?.email ?? null}
          connectedAt={gcalStatus?.connected_at ?? null}
          settingsOpen={gcalSettingsOpen}
          onToggleSettings={() => setGcalSettingsOpen((v) => !v)}
          onConnect={handleGcalConnect}
          timezone={timezone}
          calendarWatch={calendarWatch}
          autoJoinUntracked={autoJoin}
          onTimezoneChange={setTimezone}
          onCalendarWatchChange={handleCalendarWatchChange}
          onAutoJoinChange={handleAutoJoinChange}
          onDisconnect={handleGcalDisconnect}
        />

        <AtsCard id={`${id}-ats`} />

        <ClaudeCard
          id={`${id}-claude`}
          endpoint={INTEGRATIONS.claude.endpoint}
          copied={claudeEndpointCopied}
          onCopy={() => {
            navigator.clipboard.writeText(INTEGRATIONS.claude.endpoint);
            setClaudeEndpointCopied(true);
            setTimeout(() => setClaudeEndpointCopied(false), 2000);
          }}
        />
      </section>
    </div>
  );
}

// --- GCal card (handles both connected and disconnected states) ---

interface GcalCardProps {
  id: string;
  loading: boolean;
  connected: boolean;
  email: string | null;
  connectedAt: string | null;
  settingsOpen: boolean;
  onToggleSettings: () => void;
  onConnect: () => void;
  timezone: string;
  calendarWatch: boolean;
  autoJoinUntracked: boolean;
  onTimezoneChange: (tz: string) => void;
  onCalendarWatchChange: (v: boolean) => void;
  onAutoJoinChange: (v: boolean) => void;
  onDisconnect: () => void;
}

function GcalCard({
  id,
  loading,
  connected,
  email,
  connectedAt,
  settingsOpen,
  onToggleSettings,
  onConnect,
  timezone,
  calendarWatch,
  autoJoinUntracked,
  onTimezoneChange,
  onCalendarWatchChange,
  onAutoJoinChange,
  onDisconnect,
}: GcalCardProps) {
  return (
    <article id={id} className="rounded-[14px] border border-border bg-white">
      <div id={`${id}-row`} className="flex flex-wrap items-start gap-4 p-4">
        <div id={`${id}-logo`}>
          <BrandIconTile
            BrandIcon={GoogleCalendarIcon}
            background="#FFFFFF"
            borderColor="#E5E5E5"
          />
        </div>
        <div id={`${id}-info`} className="min-w-0 flex-1">
          <div id={`${id}-head`} className="flex flex-wrap items-center gap-2">
            <h3
              id={`${id}-title`}
              className="font-medium font-sans text-[15px] text-text-primary leading-tight"
            >
              Google Calendar
            </h3>
            {loading ? (
              <Skeleton id={`${id}-badge`} className="h-[18px] w-20" rounded="pill" />
            ) : connected ? (
              <span
                id={`${id}-badge`}
                className="inline-flex items-center gap-1 rounded-full border border-[#A7F3D0] bg-[#ECFDF5] px-2 py-0.5 font-mono text-[#047857] text-[9.5px] uppercase tracking-[0.14em]"
              >
                <Check strokeWidth={1.75} className="h-2.5 w-2.5" />
                Connected
              </span>
            ) : (
              <span
                id={`${id}-badge`}
                className="inline-flex items-center rounded-full border border-border bg-surface px-2 py-0.5 font-mono text-[9.5px] text-text-muted uppercase tracking-[0.14em]"
              >
                Not connected
              </span>
            )}
          </div>
          <p id={`${id}-desc`} className="mt-1 text-[12.5px] text-text-muted leading-[1.55]">
            OpenRecruiting detects interview events, attaches recordings, and suggests panel slots.
          </p>
          {connected && (email || connectedAt) && (
            <ul id={`${id}-meta`} className="mt-2 flex flex-wrap gap-4 text-[12px] text-text-muted">
              {email && (
                <li id={`${id}-meta-account`} className="flex items-center gap-1.5">
                  <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
                    Account
                  </span>
                  <span className="font-medium text-text-primary">{email}</span>
                </li>
              )}
              {connectedAt && (
                <li id={`${id}-meta-connected`} className="flex items-center gap-1.5">
                  <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
                    Connected
                  </span>
                  <span className="font-medium text-text-primary">
                    {formatRelativeTime(connectedAt)}
                  </span>
                </li>
              )}
            </ul>
          )}
        </div>

        {!loading &&
          (connected ? (
            <button
              id={`${id}-settings-toggle`}
              type="button"
              onClick={onToggleSettings}
              aria-expanded={settingsOpen}
              className={cn(
                'inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 font-medium font-sans text-[12.5px] transition-colors',
                settingsOpen
                  ? 'border-text-primary bg-text-primary text-white hover:bg-[#222]'
                  : 'border-text-primary bg-white text-text-primary hover:bg-surface',
              )}
            >
              <Settings strokeWidth={1.75} className="h-3.5 w-3.5" />
              Settings
              <ChevronDown
                strokeWidth={1.75}
                className={cn('h-3 w-3 transition-transform', settingsOpen && 'rotate-180')}
              />
            </button>
          ) : (
            <button
              id={`${id}-connect`}
              type="button"
              onClick={onConnect}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-text-primary bg-text-primary px-3.5 py-1.5 font-medium font-sans text-[12.5px] text-white transition-colors hover:bg-[#222]"
            >
              <Plug strokeWidth={1.75} className="h-3.5 w-3.5" />
              Connect
            </button>
          ))}
      </div>

      {connected && settingsOpen && (
        <div id={`${id}-settings-panel`} className="border-border border-t bg-surface/40 p-4">
          <GcalSettings
            id={`${id}-settings`}
            timezone={timezone}
            calendarWatch={calendarWatch}
            autoJoinUntracked={autoJoinUntracked}
            onTimezoneChange={onTimezoneChange}
            onCalendarWatchChange={onCalendarWatchChange}
            onAutoJoinChange={onAutoJoinChange}
            onDisconnect={onDisconnect}
          />
        </div>
      )}
    </article>
  );
}

// --- Slack card ---

interface SlackCardProps {
  id: string;
  loading: boolean;
  connected: boolean;
  teamName: string | null;
  connectedAt: string | null;
  needsReauth: boolean;
  settingsOpen: boolean;
  onToggleSettings: () => void;
  onConnect: () => void;
  onDisconnect: () => void;
}

function SlackCard({
  id,
  loading,
  connected,
  teamName,
  connectedAt,
  needsReauth,
  settingsOpen,
  onToggleSettings,
  onConnect,
  onDisconnect,
}: SlackCardProps) {
  return (
    <article id={id} className="rounded-[14px] border border-border bg-white">
      <div id={`${id}-row`} className="flex flex-wrap items-start gap-4 p-4">
        <div id={`${id}-logo`}>
          <BrandIconTile BrandIcon={SlackIcon} background="#FFFFFF" borderColor="#E5E5E5" />
        </div>
        <div id={`${id}-info`} className="min-w-0 flex-1">
          <div id={`${id}-head`} className="flex flex-wrap items-center gap-2">
            <h3
              id={`${id}-title`}
              className="font-medium font-sans text-[15px] text-text-primary leading-tight"
            >
              Slack
            </h3>
            {loading ? (
              <Skeleton id={`${id}-badge`} className="h-[18px] w-20" rounded="pill" />
            ) : connected && needsReauth ? (
              <span
                id={`${id}-badge`}
                className="inline-flex items-center rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 font-mono text-amber-700 text-[9.5px] uppercase tracking-[0.14em]"
              >
                Needs reauth
              </span>
            ) : connected ? (
              <span
                id={`${id}-badge`}
                className="inline-flex items-center gap-1 rounded-full border border-[#A7F3D0] bg-[#ECFDF5] px-2 py-0.5 font-mono text-[#047857] text-[9.5px] uppercase tracking-[0.14em]"
              >
                <Check strokeWidth={1.75} className="h-2.5 w-2.5" />
                Connected
              </span>
            ) : (
              <span
                id={`${id}-badge`}
                className="inline-flex items-center rounded-full border border-border bg-surface px-2 py-0.5 font-mono text-[9.5px] text-text-muted uppercase tracking-[0.14em]"
              >
                Not connected
              </span>
            )}
          </div>
          <p id={`${id}-desc`} className="mt-1 text-[12.5px] text-text-muted leading-[1.55]">
            Interact with OpenRecruiting directly from your team DMs.
          </p>
          {connected && (teamName || connectedAt) && (
            <ul id={`${id}-meta`} className="mt-2 flex flex-wrap gap-4 text-[12px] text-text-muted">
              {teamName && (
                <li id={`${id}-meta-workspace`} className="flex items-center gap-1.5">
                  <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
                    Workspace
                  </span>
                  <span className="font-medium text-text-primary">{teamName}</span>
                </li>
              )}
              {connectedAt && (
                <li id={`${id}-meta-connected`} className="flex items-center gap-1.5">
                  <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
                    Connected
                  </span>
                  <span className="font-medium text-text-primary">
                    {formatRelativeTime(connectedAt)}
                  </span>
                </li>
              )}
            </ul>
          )}
        </div>
        {!loading &&
          (connected ? (
            <button
              id={`${id}-settings-toggle`}
              type="button"
              onClick={onToggleSettings}
              aria-expanded={settingsOpen}
              className={cn(
                'inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 font-medium font-sans text-[12.5px] transition-colors',
                settingsOpen
                  ? 'border-text-primary bg-text-primary text-white hover:bg-[#222]'
                  : 'border-text-primary bg-white text-text-primary hover:bg-surface',
              )}
            >
              <Settings strokeWidth={1.75} className="h-3.5 w-3.5" />
              Settings
              <ChevronDown
                strokeWidth={1.75}
                className={cn('h-3 w-3 transition-transform', settingsOpen && 'rotate-180')}
              />
            </button>
          ) : (
            <button
              id={`${id}-connect`}
              type="button"
              onClick={onConnect}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-text-primary bg-text-primary px-3.5 py-1.5 font-medium font-sans text-[12.5px] text-white transition-colors hover:bg-[#222]"
            >
              <Plug strokeWidth={1.75} className="h-3.5 w-3.5" />
              Connect
            </button>
          ))}
      </div>
      {connected && settingsOpen && (
        <div id={`${id}-settings-panel`} className="border-border border-t bg-surface/40 p-4">
          <div id={`${id}-settings`} className="flex items-center gap-2">
            <button
              id={`${id}-disconnect`}
              type="button"
              onClick={onDisconnect}
              className="inline-flex items-center rounded-full border border-border bg-white px-3 py-1.5 font-medium font-sans text-[12px] text-text-muted transition-colors hover:border-text-primary hover:text-text-primary"
            >
              Disconnect Slack
            </button>
          </div>
        </div>
      )}
    </article>
  );
}

interface ClaudeCardProps {
  id: string;
  endpoint: string;
  copied: boolean;
  onCopy: () => void;
}

function ClaudeCard({ id, endpoint, copied, onCopy }: ClaudeCardProps) {
  return (
    <article id={id} className="rounded-[14px] border border-border bg-white">
      <div id={`${id}-row`} className="flex flex-wrap items-start gap-4 p-4">
        <div id={`${id}-logo`}>
          <BrandIconTile BrandIcon={ClaudeIcon} background="#FFFFFF" borderColor="#E5E5E5" />
        </div>
        <div id={`${id}-info`} className="min-w-0 flex-1">
          <div id={`${id}-head`} className="flex flex-wrap items-center gap-2">
            <h3
              id={`${id}-title`}
              className="font-medium font-sans text-[15px] text-text-primary leading-tight"
            >
              Claude
            </h3>
            <span
              id={`${id}-badge`}
              className="inline-flex items-center rounded-full border border-border bg-surface px-2 py-0.5 font-mono text-[9.5px] text-text-muted uppercase tracking-[0.14em]"
            >
              MCP
            </span>
          </div>
          <p id={`${id}-desc`} className="mt-1 text-[12.5px] text-text-muted leading-[1.55]">
            Query candidates, roles, and pipeline context directly from any Claude session via the
            Cortex MCP server.
          </p>

          <div id={`${id}-endpoint`} className="mt-3 flex items-center gap-2">
            <code className="flex-1 rounded-[8px] border border-border bg-surface px-3 py-1.5 font-mono text-[11.5px] text-text-primary truncate">
              {endpoint}
            </code>
            <button
              id={`${id}-copy`}
              type="button"
              onClick={onCopy}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-border bg-white px-3 py-1.5 font-medium font-sans text-[12px] text-text-muted transition-colors hover:border-text-primary hover:text-text-primary"
            >
              {copied ? (
                <>
                  <Check strokeWidth={1.75} className="h-3.5 w-3.5 text-[#047857]" />
                  <span className="text-[#047857]">Copied</span>
                </>
              ) : (
                <>
                  <Copy strokeWidth={1.75} className="h-3.5 w-3.5" />
                  Copy
                </>
              )}
            </button>
          </div>

          <ol id={`${id}-steps`} className="mt-4 flex flex-col gap-1.5">
            <p className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em] mb-1">
              How to connect
            </p>
            {[
              'Open Claude → Settings → Connectors',
              'Click "Add custom connector"',
              'Paste the endpoint URL above and click Add',
              'Claude will prompt you to sign in to OpenRecruiting',
            ].map((step, i) => (
              <li key={step} className="flex items-start gap-2 text-[12px] text-text-muted">
                <span className="font-mono text-[10px] text-text-faint mt-0.5">{i + 1}.</span>
                {step}
              </li>
            ))}
          </ol>
        </div>
      </div>
    </article>
  );
}

function BrandIconTile({
  BrandIcon,
  background,
  borderColor,
}: {
  BrandIcon: BrandIconComponent;
  background: string;
  borderColor: string;
}) {
  return (
    <div
      aria-hidden
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] border"
      style={{ background, borderColor }}
    >
      <BrandIcon className="h-5 w-5" />
    </div>
  );
}

interface GcalSettingsProps {
  id: string;
  timezone: string;
  calendarWatch: boolean;
  autoJoinUntracked: boolean;
  onTimezoneChange: (tz: string) => void;
  onCalendarWatchChange: (v: boolean) => void;
  onAutoJoinChange: (v: boolean) => void;
  onDisconnect: () => void;
}

function GcalSettings({
  id,
  timezone,
  calendarWatch,
  autoJoinUntracked,
  onTimezoneChange,
  onCalendarWatchChange,
  onAutoJoinChange,
  onDisconnect,
}: GcalSettingsProps) {
  return (
    <div id={id} className="flex flex-col gap-3">
      <div id={`${id}-field-tz`} className="flex flex-col gap-1.5">
        <label
          id={`${id}-field-tz-label`}
          htmlFor={`${id}-field-tz-select`}
          className="font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]"
        >
          Timezone
        </label>
        <select
          id={`${id}-field-tz-select`}
          value={timezone}
          onChange={(e) => onTimezoneChange(e.target.value)}
          className="max-w-xs rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary focus:border-text-primary focus:outline-none"
        >
          {COMMON_TIMEZONES.map((tz) => (
            <option key={tz} value={tz}>
              {tz.replace(/_/g, ' ')}
            </option>
          ))}
        </select>
      </div>
      <div id={`${id}-field-watch`} className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div
            id={`${id}-field-watch-label`}
            className="font-medium font-sans text-[12.5px] text-text-primary"
          >
            Watch calendar
          </div>
          <p
            id={`${id}-field-watch-desc`}
            className="mt-0.5 text-[11.5px] text-text-muted leading-[1.5]"
          >
            Auto-detect interviews scheduled from Google.
          </p>
        </div>
        <Toggle
          id={`${id}-field-watch-toggle`}
          checked={calendarWatch}
          onChange={onCalendarWatchChange}
          ariaLabel="Watch calendar"
        />
      </div>
      <div id={`${id}-field-auto`} className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div
            id={`${id}-field-auto-label`}
            className="font-medium font-sans text-[12.5px] text-text-primary"
          >
            Auto-join untracked interviews
          </div>
          <p
            id={`${id}-field-auto-desc`}
            className="mt-0.5 text-[11.5px] text-text-muted leading-[1.5]"
          >
            Let OpenRecruiting hop into events it has not seen before.
          </p>
        </div>
        <Toggle
          id={`${id}-field-auto-toggle`}
          checked={autoJoinUntracked}
          onChange={onAutoJoinChange}
          ariaLabel="Auto-join untracked interviews"
        />
      </div>
      <div id={`${id}-actions`} className="flex items-center gap-2 pt-2">
        <button
          id={`${id}-disconnect`}
          type="button"
          onClick={onDisconnect}
          className="inline-flex items-center rounded-full border border-border bg-white px-3 py-1.5 font-medium font-sans text-[12px] text-text-muted transition-colors hover:border-text-primary hover:text-text-primary"
        >
          Disconnect Google Calendar
        </button>
      </div>
    </div>
  );
}

interface ToggleProps {
  id: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  ariaLabel: string;
}

function Toggle({ id, checked, onChange, ariaLabel }: ToggleProps) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors',
        checked ? 'border-text-primary bg-text-primary' : 'border-border bg-surface',
      )}
    >
      <span
        id={`${id}-thumb`}
        aria-hidden
        className={cn(
          'inline-block h-3.5 w-3.5 translate-x-[3px] rounded-full bg-white shadow-sm transition-transform',
          checked && 'translate-x-[18px]',
        )}
      />
    </button>
  );
}
