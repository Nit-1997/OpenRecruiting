'use client';

import { useCallback, useEffect, useState } from 'react';
import { useToast } from '@/components/ui/toast';
import {
  type AtsRequisitionSync,
  applyAtsUpdate,
  dismissAtsUpdate,
  getRequisitionAtsSync,
} from '@/services/integrations-ats';

function providerLabel(provider: string | null): string {
  if (!provider) return 'ATS';
  return provider.charAt(0).toUpperCase() + provider.slice(1);
}

const FIELD_LABELS: Record<string, string> = {
  role_title: 'Title',
  role_location: 'Location',
  job_description: 'Job description',
  experience_min_years: 'Min experience',
  experience_max_years: 'Max experience',
};

interface AtsUpdateChipProps {
  id: string;
  requisitionId: string;
  /** Called after a successful Apply so the page can refetch role data. */
  onApplied?: () => void;
}

/**
 * "Updated in <ATS> — review" chip for published requisitions whose linked
 * ATS job changed (ats_dirty) or was removed (ats_deleted). Renders nothing
 * for unlinked/clean requisitions; failures stay silent here because the
 * chip is auxiliary (the role page itself must not degrade).
 */
export function AtsUpdateChip({ id, requisitionId, onApplied }: AtsUpdateChipProps) {
  const { showToast } = useToast();
  const [sync, setSync] = useState<AtsRequisitionSync | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setSync(await getRequisitionAtsSync(requisitionId));
    } catch {
      setSync(null);
    }
  }, [requisitionId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (!sync?.linked || (!sync.ats_dirty && !sync.ats_deleted)) return null;

  const provider = providerLabel(sync.provider);

  if (sync.ats_deleted && !sync.ats_dirty) {
    return (
      <span
        id={id}
        className="inline-flex items-center rounded-full border border-border bg-surface px-2.5 py-1 font-mono text-[10px] text-text-muted uppercase tracking-[0.14em]"
      >
        Removed in {provider}
      </span>
    );
  }

  async function handleApply() {
    setBusy(true);
    try {
      await applyAtsUpdate(requisitionId);
      await refresh();
      showToast(`Applied the latest ${provider} changes.`, 'success');
      onApplied?.();
    } catch {
      showToast('Failed to apply the ATS update. Please try again.', 'error');
    } finally {
      setBusy(false);
    }
  }

  async function handleDismiss() {
    setBusy(true);
    try {
      await dismissAtsUpdate(requisitionId);
      await refresh();
    } catch {
      showToast('Failed to dismiss the ATS update. Please try again.', 'error');
    } finally {
      setBusy(false);
    }
  }

  const changes = Object.entries(sync.pending_changes ?? {});

  return (
    <div id={id} className="inline-flex flex-col gap-2">
      <button
        id={`${id}-toggle`}
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 font-mono text-[10px] text-amber-700 uppercase tracking-[0.14em] transition-colors hover:bg-amber-100"
      >
        Updated in {provider} — review
      </button>
      {expanded && (
        <div
          id={`${id}-panel`}
          className="rounded-[12px] border border-border bg-white p-3 text-[12.5px]"
        >
          <ul id={`${id}-changes`} className="flex flex-col gap-1.5">
            {changes.map(([field, value]) => (
              <li id={`${id}-change-${field}`} key={field} className="flex gap-2">
                <span className="shrink-0 font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
                  {FIELD_LABELS[field] ?? field}
                </span>
                <span className="min-w-0 break-words text-text-primary">{String(value)}</span>
              </li>
            ))}
          </ul>
          <div id={`${id}-actions`} className="mt-3 flex items-center gap-2">
            <button
              id={`${id}-apply`}
              type="button"
              disabled={busy}
              onClick={handleApply}
              className="inline-flex items-center rounded-full border border-text-primary bg-text-primary px-3 py-1 font-medium font-sans text-[12px] text-white transition-colors hover:bg-[#222] disabled:opacity-50"
            >
              Apply
            </button>
            <button
              id={`${id}-dismiss`}
              type="button"
              disabled={busy}
              onClick={handleDismiss}
              className="inline-flex items-center rounded-full border border-border bg-white px-3 py-1 font-medium font-sans text-[12px] text-text-primary transition-colors hover:bg-surface disabled:opacity-50"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
