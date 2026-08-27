'use client';

import { Check, Loader2, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { AshbyIcon, GreenhouseIcon } from '@/components/icons/brand-icons';
import { cn } from '@/lib/utils';
import { candidates } from '@/services';
import { ServiceError } from '@/services/service-error';

export type AtsProvider = 'ashby' | 'greenhouse';

interface ImportFromAtsModalProps {
  id: string;
  roleId: string;
  roleTitle: string;
  provider: AtsProvider;
  onClose: () => void;
}

interface AtsStubCandidate {
  name: string;
  email: string;
  previousCompany: string;
  stage: string;
}

const ASHBY_STUBS: AtsStubCandidate[] = [
  {
    name: 'Sloane Ellis',
    email: 'priya.sharma@example.com',
    previousCompany: 'Figma',
    stage: 'Applied · 2d ago',
  },
  {
    name: 'Miguel Alvarado',
    email: 'miguel.alvarado@example.com',
    previousCompany: 'Linear',
    stage: 'Applied · 4d ago',
  },
  {
    name: 'Esther Lin',
    email: 'esther.lin@example.com',
    previousCompany: 'Notion',
    stage: 'Applied · 1w ago',
  },
  {
    name: 'Arnav Patel',
    email: 'arnav.patel@example.com',
    previousCompany: 'Vercel',
    stage: 'Applied · 1w ago',
  },
  {
    name: 'Zoë Kowalski',
    email: 'zoe.kowalski@example.com',
    previousCompany: 'Retool',
    stage: 'Applied · 2w ago',
  },
  {
    name: 'Demetri Roux',
    email: 'demetri.roux@example.com',
    previousCompany: 'Mercury',
    stage: 'Applied · 2w ago',
  },
];

const GREENHOUSE_STUBS: AtsStubCandidate[] = [
  {
    name: 'Yara Okafor',
    email: 'yara.okafor@example.com',
    previousCompany: 'Lattice',
    stage: 'Applied · 3d ago',
  },
  {
    name: 'Kenji Watanabe',
    email: 'kenji.watanabe@example.com',
    previousCompany: 'Airbase',
    stage: 'Applied · 5d ago',
  },
  {
    name: 'Saoirse Mulligan',
    email: 'saoirse.mulligan@sentry.io',
    previousCompany: 'Sentry',
    stage: 'Applied · 1w ago',
  },
  {
    name: 'Luca Greco',
    email: 'luca.greco@segment.com',
    previousCompany: 'Segment',
    stage: 'Applied · 2w ago',
  },
  {
    name: 'Amira Ben Saïd',
    email: 'amira.bensaid@example.com',
    previousCompany: 'Coda',
    stage: 'Applied · 2w ago',
  },
  {
    name: 'Ravi Balasubramanian',
    email: 'ravi.b@example.com',
    previousCompany: 'Notion',
    stage: 'Applied · 3w ago',
  },
];

const PROVIDER_META: Record<
  AtsProvider,
  { label: string; icon: typeof AshbyIcon; stubs: AtsStubCandidate[] }
> = {
  ashby: { label: 'Ashby', icon: AshbyIcon, stubs: ASHBY_STUBS },
  greenhouse: { label: 'Greenhouse', icon: GreenhouseIcon, stubs: GREENHOUSE_STUBS },
};

export function ImportFromAtsModal({
  id,
  roleId,
  roleTitle,
  provider,
  onClose,
}: ImportFromAtsModalProps) {
  const { label, icon: ProviderIcon, stubs } = PROVIDER_META[provider];
  const [selected, setSelected] = useState<Set<string>>(() => new Set(stubs.map((s) => s.email)));
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedCount = selected.size;

  const toggle = (email: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(email)) next.delete(email);
      else next.add(email);
      return next;
    });
  };

  const picks = useMemo(() => stubs.filter((s) => selected.has(s.email)), [stubs, selected]);

  const handleImport = async () => {
    if (busy || picks.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      for (const p of picks) {
        try {
          await candidates.create(roleId, {
            name: p.name,
            email: p.email,
            source: provider,
            tags: [p.previousCompany, provider],
          });
        } catch (err) {
          if (err instanceof ServiceError && err.code === 'conflict') {
            continue;
          }
          throw err;
        }
      }
      setDone(true);
      setTimeout(() => onClose(), 900);
    } catch (err) {
      setError(err instanceof ServiceError ? err.message : 'Import failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      id={id}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
    >
      <div className="flex max-h-[85vh] w-full max-w-lg flex-col overflow-hidden rounded-[16px] border border-border bg-white shadow-[0_20px_60px_rgba(0,0,0,0.2)]">
        <header className="flex items-start justify-between gap-3 border-border border-b px-5 py-4">
          <div className="flex items-center gap-3">
            <ProviderIcon id={`${id}-brand`} className="h-9 w-9" />
            <div>
              <h2 className="font-display text-[20px] text-text-primary leading-tight">
                Import from {label}
              </h2>
              <p className="mt-0.5 font-mono text-[11px] text-text-muted uppercase tracking-[0.14em]">
                Connected · {stubs.length} matches for {roleTitle}
              </p>
            </div>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-full text-text-muted hover:text-text-primary"
          >
            <X strokeWidth={1.75} className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          <ul className="flex flex-col gap-2">
            {stubs.map((s) => {
              const checked = selected.has(s.email);
              return (
                <li
                  key={s.email}
                  id={`${id}-row-${s.email}`}
                  className={cn(
                    'flex items-center gap-3 rounded-[12px] border p-3 transition-colors',
                    checked
                      ? 'border-text-primary bg-surface/80'
                      : 'border-border bg-white hover:bg-surface/40',
                  )}
                >
                  <label
                    className={cn(
                      'flex h-5 w-5 shrink-0 cursor-pointer items-center justify-center rounded-[6px] border transition-colors',
                      checked
                        ? 'border-text-primary bg-text-primary text-white'
                        : 'border-border bg-white text-transparent',
                    )}
                  >
                    <input
                      type="checkbox"
                      className="sr-only"
                      checked={checked}
                      onChange={() => toggle(s.email)}
                    />
                    <Check strokeWidth={2.25} className="h-3 w-3" />
                  </label>
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium text-[13.5px] text-text-primary">
                      {s.name}
                    </div>
                    <div className="truncate text-[12px] text-text-muted">
                      {s.previousCompany} · {s.email}
                    </div>
                  </div>
                  <span className="shrink-0 font-mono text-[10px] text-text-muted uppercase tracking-[0.14em]">
                    {s.stage}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>

        {error && (
          <p className="border-border border-t bg-[#FEF2F2] px-5 py-2 text-[#B91C1C] text-[12.5px]">
            {error}
          </p>
        )}

        <footer className="flex items-center justify-between gap-2 border-border border-t bg-surface/60 px-5 py-3">
          <span className="text-[12.5px] text-text-muted">{selectedCount} selected</span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-full border border-border bg-white px-3.5 py-1.5 text-[12.5px] text-text-primary hover:border-text-primary"
            >
              Cancel
            </button>
            <button
              id={`${id}-import`}
              type="button"
              onClick={handleImport}
              disabled={busy || selectedCount === 0 || done}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 font-medium text-[12.5px] transition-colors',
                busy || selectedCount === 0 || done
                  ? 'cursor-not-allowed border border-border bg-surface text-text-faint'
                  : 'border border-text-primary bg-text-primary text-white hover:bg-[#222]',
              )}
            >
              {busy ? (
                <>
                  <Loader2 strokeWidth={1.75} className="h-3.5 w-3.5 animate-spin" />
                  Importing…
                </>
              ) : done ? (
                <>
                  <Check strokeWidth={2} className="h-3.5 w-3.5" />
                  Imported
                </>
              ) : (
                <>Import {selectedCount} to pipeline</>
              )}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
