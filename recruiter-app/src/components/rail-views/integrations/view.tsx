'use client';

import { Check, Copy } from 'lucide-react';
import type { ComponentType } from 'react';
import { useState } from 'react';
import { ClaudeIcon } from '@/components/icons/brand-icons';
import { useShellSync } from '@/hooks/use-shell-sync';
import { getRuntimeConfig } from '@/lib/runtime-config';
import { AtsCard } from './ats-card';

type BrandIconComponent = ComponentType<{ className?: string; id?: string }>;

interface IntegrationsViewProps {
  id: string;
}

export function IntegrationsView({ id }: IntegrationsViewProps) {
  useShellSync();

  const [claudeEndpointCopied, setClaudeEndpointCopied] = useState(false);
  // Runtime, not a fixture: this URL is resolved by Claude's servers, so it has
  // to be the public tunnel host. It used to be a hardcoded localhost literal
  // that no deployment could ever have used.
  const claudeEndpoint = getRuntimeConfig().cortexMcpUrl;

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

        <AtsCard id={`${id}-ats`} />

        <ClaudeCard
          id={`${id}-claude`}
          endpoint={claudeEndpoint}
          copied={claudeEndpointCopied}
          onCopy={() => {
            if (!claudeEndpoint) return;
            navigator.clipboard.writeText(claudeEndpoint);
            setClaudeEndpointCopied(true);
            setTimeout(() => setClaudeEndpointCopied(false), 2000);
          }}
        />
      </section>
    </div>
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
            <code
              className={`flex-1 truncate rounded-[8px] border border-border bg-surface px-3 py-1.5 font-mono text-[11.5px] ${
                endpoint ? 'text-text-primary' : 'text-text-faint'
              }`}
            >
              {endpoint || 'NEXT_PUBLIC_CORTEX_MCP_URL is not set'}
            </code>
            <button
              id={`${id}-copy`}
              type="button"
              onClick={onCopy}
              disabled={!endpoint}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-border bg-white px-3 py-1.5 font-medium font-sans text-[12px] text-text-muted transition-colors hover:border-text-primary hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-border disabled:hover:text-text-muted"
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
