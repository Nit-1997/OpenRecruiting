'use client';

import { Check, Plug } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { Skeleton } from '@/components/shell/primitives/skeleton';
import { useConfirm } from '@/components/ui/confirm-dialog';
import { useToast } from '@/components/ui/toast';
import {
  type AtsStatus,
  completeAtsConnection,
  disconnectAts,
  getAtsSessionToken,
  getAtsStatus,
  type KnitIntegrationDetails,
} from '@/services/integrations-ats';
import { formatRelativeTime } from './relative-time';

const KNIT_SCRIPT_ID = 'knit-ui-comp-script';
const KNIT_SCRIPT_SRC = 'https://af1.getknit.dev/knit-ui-comp.js';

function loadKnitScript(): void {
  if (document.getElementById(KNIT_SCRIPT_ID)) return;
  const script = document.createElement('script');
  script.id = KNIT_SCRIPT_ID;
  script.type = 'module';
  script.src = KNIT_SCRIPT_SRC;
  document.head.appendChild(script);
}

function providerLabel(provider: string | null): string {
  if (!provider) return '';
  return provider.charAt(0).toUpperCase() + provider.slice(1);
}

interface AtsCardProps {
  id: string;
}

export function AtsCard({ id }: AtsCardProps) {
  const { showToast } = useToast();
  const confirm = useConfirm();
  // Callback-ref-into-state: the knit-auth element renders only after status
  // resolves to "not connected", so listeners must attach when it APPEARS,
  // not on first mount (a plain useRef would miss it).
  const [knitNode, setKnitNode] = useState<HTMLElement | null>(null);

  const [status, setStatus] = useState<AtsStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState(false);

  const refreshStatus = useCallback(async () => {
    try {
      const next = await getAtsStatus();
      setStatus(next);
      setUnavailable(false);
    } catch (err) {
      // Structural check, not instanceof: bun's process-wide mock.module can
      // swap class identities across test files (see CLAUDE.md), and the
      // ServiceError contract guarantees `.code`.
      if ((err as { code?: string } | null)?.code === 'not_found') {
        setUnavailable(true);
      } else {
        showToast('Failed to load ATS connection status.', 'error');
      }
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    loadKnitScript();
    void refreshStatus();
  }, [refreshStatus]);

  const fetchSessionToken = useCallback(async () => {
    try {
      const token = await getAtsSessionToken();
      knitNode?.setAttribute('authsessiontoken', token);
    } catch {
      showToast('Failed to start the ATS connection. Please try again.', 'error');
    }
  }, [knitNode, showToast]);

  const connected = !loading && !unavailable && status?.connected === true;

  useEffect(() => {
    const node = knitNode;
    if (!node || connected) return;

    const onNewSession = (e: Event) => {
      e.preventDefault();
      void fetchSessionToken();
    };
    const onFinish = (e: Event) => {
      e.preventDefault();
      const details = (e as CustomEvent).detail?.integrationDetails as
        | KnitIntegrationDetails
        | undefined;
      if (!details?.success) {
        showToast('ATS connection was not completed.', 'error');
        return;
      }
      completeAtsConnection(details)
        .then((next) => {
          setStatus(next);
          const summary = next.import_summary;
          if (summary) {
            const provider = providerLabel(next.provider) || 'your ATS';
            const skipped = summary.skipped_closed
              ? ` — ${summary.skipped_closed} skipped (closed)`
              : '';
            showToast(
              `Imported ${summary.created} job${summary.created === 1 ? '' : 's'} from ${provider}${skipped}.`,
              'success',
            );
          } else {
            showToast('ATS connected.', 'success');
          }
        })
        .catch(() => {
          showToast('Could not verify the ATS connection. Please try again.', 'error');
        });
    };
    const onDeactivate = () => {
      void refreshStatus();
    };

    node.addEventListener('onNewSession', onNewSession);
    node.addEventListener('onFinish', onFinish);
    node.addEventListener('onDeactivate', onDeactivate);
    void fetchSessionToken();
    return () => {
      node.removeEventListener('onNewSession', onNewSession);
      node.removeEventListener('onFinish', onFinish);
      node.removeEventListener('onDeactivate', onDeactivate);
    };
  }, [knitNode, connected, fetchSessionToken, refreshStatus, showToast]);

  async function handleDisconnect() {
    const provider = providerLabel(status?.provider ?? null) || 'your ATS';
    const ok = await confirm({
      title: `Disconnect ${provider}?`,
      body: 'OpenRecruiting will stop reading jobs and candidates from this ATS.',
      confirmLabel: 'Disconnect',
      danger: true,
    });
    if (!ok) return;
    try {
      await disconnectAts();
      await refreshStatus();
      showToast('ATS disconnected.', 'success');
    } catch {
      showToast('Failed to disconnect the ATS. Please try again.', 'error');
    }
  }

  return (
    <article id={id} className="rounded-[14px] border border-border bg-white">
      <div id={`${id}-row`} className="flex flex-wrap items-start gap-4 p-4">
        <div
          id={`${id}-logo`}
          aria-hidden
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] border border-[#E5E5E5] bg-white"
        >
          <Plug strokeWidth={1.75} className="h-5 w-5 text-text-primary" />
        </div>
        <div id={`${id}-info`} className="min-w-0 flex-1">
          <div id={`${id}-head`} className="flex flex-wrap items-center gap-2">
            <h3
              id={`${id}-title`}
              className="font-medium font-sans text-[15px] text-text-primary leading-tight"
            >
              {connected ? providerLabel(status?.provider ?? null) : 'Applicant Tracking System'}
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
            ) : unavailable ? (
              <span
                id={`${id}-badge`}
                className="inline-flex items-center rounded-full border border-border bg-surface px-2 py-0.5 font-mono text-[9.5px] text-text-muted uppercase tracking-[0.14em]"
              >
                Coming soon
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
            Import jobs and candidates from Workable, Ashby, Greenhouse, Lever and more.
          </p>
          {connected && (
            <ul id={`${id}-meta`} className="mt-2 flex flex-wrap gap-4 text-[12px] text-text-muted">
              {status?.connected_at && (
                <li id={`${id}-meta-connected`} className="flex items-center gap-1.5">
                  <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
                    Connected
                  </span>
                  <span className="font-medium text-text-primary">
                    {formatRelativeTime(status.connected_at)}
                  </span>
                </li>
              )}
              {status?.connected_by_name && (
                <li id={`${id}-meta-by`} className="flex items-center gap-1.5">
                  <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
                    By
                  </span>
                  <span className="font-medium text-text-primary">{status.connected_by_name}</span>
                </li>
              )}
            </ul>
          )}
        </div>
        {!loading &&
          !unavailable &&
          (connected ? (
            <button
              id={`${id}-disconnect`}
              type="button"
              onClick={handleDisconnect}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-border bg-white px-3.5 py-1.5 font-medium font-sans text-[12.5px] text-text-primary transition-colors hover:bg-surface"
            >
              Disconnect
            </button>
          ) : (
            <knit-auth ref={setKnitNode}>
              <button
                id={`${id}-connect`}
                slot="trigger"
                type="button"
                className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-text-primary bg-text-primary px-3.5 py-1.5 font-medium font-sans text-[12.5px] text-white transition-colors hover:bg-[#222]"
              >
                <Plug strokeWidth={1.75} className="h-3.5 w-3.5" />
                Connect
              </button>
            </knit-auth>
          ))}
      </div>
    </article>
  );
}
