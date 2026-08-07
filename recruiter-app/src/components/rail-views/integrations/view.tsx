'use client';

import { Check, ChevronDown, Copy, Plug, Settings } from 'lucide-react';
import type { ComponentType } from 'react';
import { useEffect, useState } from 'react';
import { ClaudeIcon, SlackIcon } from '@/components/icons/brand-icons';
import { Skeleton } from '@/components/shell/primitives/skeleton';
import { useToast } from '@/components/ui/toast';
import { INTEGRATIONS } from '@/fixtures/integrations';
import { useShellSync } from '@/hooks/use-shell-sync';
import { cn } from '@/lib/utils';
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

  const [claudeEndpointCopied, setClaudeEndpointCopied] = useState(false);

  // Load real status on mount and handle OAuth callback params
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const slackParam = params.get('slack');

    if (slackParam) {
      const url = new URL(window.location.href);
      url.searchParams.delete('slack');
      url.searchParams.delete('reason');
      window.history.replaceState({}, '', url.toString());

      if (slackParam === 'error') {
        const reason = params.get('reason') ?? 'unknown';
        showToast(`Slack connection failed: ${reason}`, 'error');
      }
    }

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
