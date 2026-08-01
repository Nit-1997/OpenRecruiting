'use client';

import { ChevronLeft, MapPin } from 'lucide-react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { type ReactNode, useEffect, useRef, useState } from 'react';
import { PacketDrawer } from '@/components/packet-drawer/drawer';
import { AtsUpdateChip } from '@/components/role-detail/ats-update-chip';
import { AtsSourceBadge } from '@/components/shared/ats-source-badge';
import { RoleDetailSkeleton } from '@/components/shell/skeletons';
import { ConfirmDialogProvider } from '@/components/ui/confirm-dialog';
import { useToast } from '@/components/ui/toast';
import type { RequisitionStatus } from '@/domain';
import { useRequisition } from '@/hooks/use-services';
import { IntakeApiError, startIntakeForRole } from '@/lib/intake/api';
import { cn } from '@/lib/utils';
import { requisitions } from '@/services';
import { ServiceError } from '@/services/service-error';
import { AddCandidateForm } from './add-candidate-form';
import { AddCandidatesMenu } from './add-candidates-menu';
import { DebriefTab } from './debrief-tab';
import { PipelineTab } from './pipeline-tab';
import { PlanTab } from './plan-tab';

type TabKey = 'pipeline' | 'plan' | 'debrief';

// 300 ms gives the auth session token time to propagate before the retry fetch,
// without making the page feel sluggish on a genuine transient 404.
const RETRY_DELAY_MS = 300;

interface RoleDetailPageProps {
  id: string;
  roleId: string;
}

export function RoleDetailPage({ id, roleId }: RoleDetailPageProps) {
  const { data: role, loading, error, refetch } = useRequisition(roleId);
  const searchParams = useSearchParams();
  // A `?debrief=<packetId>` handoff link (from the agent's Save step) lands on
  // the Debrief tab so DebriefTab's existing `?debrief=` effect can auto-open
  // the packet once the list resolves. Otherwise default to Pipeline.
  const [tab, setTab] = useState<TabKey>(() =>
    searchParams?.get('debrief') ? 'debrief' : 'pipeline',
  );
  const [packet, setPacket] = useState<{ candidateId: string; roundId: string | null } | null>(
    null,
  );
  const [addManuallyOpen, setAddManuallyOpen] = useState(false);

  // One-shot retry: if the first fetch errors (transient auth/session race),
  // wait RETRY_DELAY_MS and re-fetch exactly once before falling through to 404 UI.
  //
  // retryFired is React state so the loader/404 UI re-renders at the right time.
  // scheduledRef is an internal guard only — prevents double-scheduling inside
  // the effect and must never gate rendered output directly.
  const [retryFired, setRetryFired] = useState(false);
  const scheduledRef = useRef(false);

  useEffect(() => {
    if (error && !loading && !role && !scheduledRef.current) {
      scheduledRef.current = true;
      const t = setTimeout(() => {
        setRetryFired(true);
        refetch();
      }, RETRY_DELAY_MS);
      return () => clearTimeout(t);
    }
    return undefined;
  }, [error, loading, role, refetch]);

  // Show the loader while:
  //   • initial fetch is in-flight
  //   • retry timer is still counting down (error present, retry not fired yet)
  //   • retry has fired and the refetch is now in-flight
  // Once retryFired && !loading, the hook has settled — fall through to role/404.
  const showLoader =
    (loading && !role) || (!retryFired && !!error && !role) || (retryFired && loading);

  if (showLoader) {
    return <RoleDetailSkeleton id={id} />;
  }

  if (error || !role) {
    return (
      <div id={id} className="pt-6 pb-8 sm:pt-10">
        <Link
          id={`${id}-back`}
          href="/view/roles"
          className="inline-flex items-center gap-1 font-mono text-[11px] text-text-muted uppercase tracking-[0.14em] hover:text-text-primary"
        >
          <ChevronLeft strokeWidth={1.75} className="h-3.5 w-3.5" />
          Back to Roles
        </Link>
        <h1 id={`${id}-missing`} className="mt-3 font-display text-[28px] text-text-primary">
          Role not found
        </h1>
        <p id={`${id}-missing-sub`} className="mt-1 text-[13.5px] text-text-muted">
          We couldn&apos;t find a role with id <code>{roleId}</code>.
        </p>
      </div>
    );
  }

  const tabs: Array<{ key: TabKey; label: string; disabled?: boolean }> = [
    { key: 'pipeline', label: 'Pipeline' },
    { key: 'plan', label: 'Plan' },
    { key: 'debrief', label: 'Debrief' },
  ];

  return (
    <ConfirmDialogProvider>
      <div id={id} className="pt-6 pb-8 sm:pt-10">
        <div id={`${id}-back-row`} className="mb-4 flex items-center gap-3">
          <Link
            id={`${id}-back`}
            href="/view/roles"
            className="group inline-flex items-center gap-1.5 rounded-full border border-border bg-white px-3 py-1.5 font-medium font-sans text-[12.5px] text-text-primary transition-colors hover:border-text-primary hover:bg-surface"
          >
            <ChevronLeft
              strokeWidth={1.75}
              className="h-3.5 w-3.5 transition-transform group-hover:-translate-x-0.5"
            />
            All roles
          </Link>
        </div>

        <header
          id={`${id}-header`}
          className="mb-6 flex flex-wrap items-end justify-between gap-3 border-border border-b pb-5"
        >
          <div id={`${id}-header-text`} className="min-w-0">
            <h1
              id={`${id}-title`}
              className="flex flex-wrap items-center gap-2.5 font-display text-[26px] text-text-primary leading-[1.1] tracking-[-0.01em] sm:text-[34px]"
            >
              {role.role_title}
              <AtsSourceBadge
                id={`${id}-ats-badge`}
                source={role.source}
                provider={role.ats_provider}
              />
            </h1>
            <div
              id={`${id}-meta`}
              className="mt-2 flex flex-wrap items-center gap-3 text-[13px] text-text-muted"
            >
              {(() => {
                const parts: ReactNode[] = [];
                if (role.role_location) {
                  parts.push(
                    <span key="loc" className="flex items-center gap-1">
                      <MapPin strokeWidth={1.75} className="h-3.5 w-3.5" />
                      {role.role_location}
                    </span>,
                  );
                }
                if (role.department) {
                  parts.push(<span key="dept">{role.department}</span>);
                }
                if (role.created_by_name) {
                  parts.push(<span key="owner">Owned by {role.created_by_name}</span>);
                }
                return parts.flatMap((node, i) =>
                  i === 0 ? [node] : [<span key={`sep-${i}`}>·</span>, node],
                );
              })()}
            </div>
            {role.source === 'ats_sync' && (
              <div id={`${id}-ats-sync-row`} className="mt-3">
                <AtsUpdateChip
                  id={`${id}-ats-update-chip`}
                  requisitionId={role.id}
                  onApplied={refetch}
                />
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            <StatusChip status={role.status} />
            <QuickActions roleId={role.id} status={role.status} />
            {role.status === 'planned' && (
              <AddCandidatesMenu
                id={`${id}-add-menu`}
                roleId={role.id}
                roleTitle={role.role_title}
                onAddManually={() => setAddManuallyOpen(true)}
              />
            )}
          </div>
        </header>

        <div
          id={`${id}-tabs`}
          role="tablist"
          className="mb-6 flex gap-1 overflow-x-auto rounded-[12px] bg-surface p-1"
        >
          {tabs.map((t) => {
            const active = tab === t.key;
            const disabled = t.disabled === true;
            return (
              <button
                key={t.key}
                id={`${id}-tab-${t.key}`}
                type="button"
                role="tab"
                aria-selected={active}
                aria-disabled={disabled}
                disabled={disabled}
                title={disabled ? 'Coming soon' : undefined}
                onClick={() => {
                  if (!disabled) setTab(t.key);
                }}
                className={cn(
                  'flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-[10px] px-3 py-1.5 font-medium font-sans text-[12.5px] transition-colors sm:flex-1',
                  disabled
                    ? 'cursor-not-allowed text-text-faint'
                    : active
                      ? 'bg-white text-text-primary shadow-[0_1px_3px_rgba(0,0,0,0.04)]'
                      : 'text-text-muted hover:text-text-primary',
                )}
              >
                {t.label}
                {disabled && (
                  <span className="rounded-full border border-border bg-white px-2 py-0.5 font-mono text-[9px] text-text-muted uppercase tracking-[0.14em]">
                    Coming soon
                  </span>
                )}
              </button>
            );
          })}
        </div>

        <div id={`${id}-body`}>
          {tab === 'pipeline' && (
            <PipelineTab
              id={`${id}-pipeline`}
              role={role}
              onCellClick={(candidateId, roundId) => setPacket({ candidateId, roundId })}
            />
          )}
          {tab === 'plan' && <PlanTab id={`${id}-plan`} role={role} />}
          {tab === 'debrief' && <DebriefTab id={`${id}-debrief`} role={role} />}
        </div>

        {packet && (
          <PacketDrawer
            id={`${id}-packet`}
            reqId={role.id}
            candidateId={packet.candidateId}
            initialRoundId={packet.roundId}
            viewOnly={role.status === 'closed'}
            onClose={() => setPacket(null)}
          />
        )}

        {addManuallyOpen && (
          <AddCandidateForm
            id={`${id}-add-form`}
            roleId={role.id}
            onClose={() => setAddManuallyOpen(false)}
          />
        )}
      </div>
    </ConfirmDialogProvider>
  );
}

function StatusChip({ status }: { status: RequisitionStatus }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-2 rounded-full border px-3 py-1 font-mono text-[10.5px] uppercase tracking-[0.14em]',
        status === 'planned'
          ? 'border-[#A7F3D0] bg-[#ECFDF5] text-[#047857]'
          : status === 'intake_pending'
            ? 'border-[#FDE68A] bg-[#FFFBEB] text-[#B45309]'
            : 'border-border bg-surface text-text-secondary',
      )}
    >
      <span
        aria-hidden
        className={cn(
          'h-1.5 w-1.5 rounded-full',
          status === 'planned'
            ? 'bg-[#10B981]'
            : status === 'intake_pending'
              ? 'bg-[#F59E0B]'
              : 'bg-text-muted',
        )}
      />
      {status.replace(/_/g, ' ')}
    </span>
  );
}

function QuickActions({ roleId, status }: { roleId: string; status: RequisitionStatus }) {
  const router = useRouter();
  const { showToast } = useToast();
  const logErr = (err: unknown) => {
    if (err instanceof ServiceError) {
      console.warn(`[role-detail] ${err.code}: ${err.message}`);
    }
  };
  // Pending roles move forward through intake, not a bare status flip:
  // the intake canvas owns plan review + publish.
  const completeIntake = async () => {
    try {
      const { session_id } = await startIntakeForRole(roleId);
      router.push(`/intake/sessions/${session_id}`);
    } catch (err) {
      showToast(err instanceof IntakeApiError ? err.detail : 'Could not start intake', 'error');
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-2">
      {status === 'intake_pending' && (
        <button
          type="button"
          onClick={() => {
            void completeIntake();
          }}
          className="rounded-full border border-text-primary bg-text-primary px-3 py-1.5 font-medium text-[12px] text-white hover:bg-[#222]"
        >
          Complete intake
        </button>
      )}
      {status === 'planned' && (
        <button
          type="button"
          onClick={() => {
            requisitions.setStatus(roleId, 'closed').catch(logErr);
          }}
          className="rounded-full border border-border bg-white px-3 py-1.5 font-medium text-[12px] text-text-primary hover:border-text-primary"
        >
          Close
        </button>
      )}
      {status === 'closed' && (
        <button
          type="button"
          onClick={() => {
            requisitions.setStatus(roleId, 'planned').catch(logErr);
          }}
          className="rounded-full border border-border bg-white px-3 py-1.5 font-medium text-[12px] text-text-primary hover:border-text-primary"
        >
          Reopen
        </button>
      )}
    </div>
  );
}
