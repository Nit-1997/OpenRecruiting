'use client';

import { ChevronDown, Plus, Radar, User } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { AshbyIcon, GreenhouseIcon } from '@/components/icons/brand-icons';
import { cn } from '@/lib/utils';
import type { AtsProvider } from './import-from-ats-modal';
import { ImportFromAtsModal } from './import-from-ats-modal';

interface AddCandidatesMenuProps {
  id: string;
  roleId: string;
  roleTitle: string;
  onAddManually: () => void;
}

export function AddCandidatesMenu({
  id,
  roleId,
  roleTitle,
  onAddManually,
}: AddCandidatesMenuProps) {
  const [open, setOpen] = useState(false);
  const [atsModal, setAtsModal] = useState<AtsProvider | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [open]);

  return (
    <div id={id} ref={ref} className="relative">
      <button
        id={`${id}-trigger`}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 rounded-full border border-text-primary bg-text-primary px-3.5 py-1.5 font-medium font-sans text-[12.5px] text-white hover:bg-[#222]"
      >
        <Plus strokeWidth={1.75} className="h-3.5 w-3.5" />
        Add candidates
        <ChevronDown strokeWidth={1.75} className="h-3.5 w-3.5" />
      </button>
      {open && (
        <div
          id={`${id}-menu`}
          role="menu"
          className="absolute top-9 right-0 z-30 flex w-[260px] flex-col overflow-hidden rounded-[12px] border border-border bg-white py-1 shadow-[0_10px_32px_rgba(0,0,0,0.12)]"
        >
          <MenuButton
            id={`${id}-manual`}
            icon={<User strokeWidth={1.75} className="h-4 w-4 text-text-muted" />}
            label="Add manually"
            sub="One-off candidate by name + email"
            onClick={() => {
              setOpen(false);
              onAddManually();
            }}
          />
          <hr className="my-1 border-border" />
          <MenuButton
            id={`${id}-ashby`}
            icon={<AshbyIcon className="h-5 w-5" />}
            label="Import from Ashby"
            sub="Pull applicants flagged for this role"
            comingSoon
            onClick={() => {}}
          />
          <MenuButton
            id={`${id}-greenhouse`}
            icon={<GreenhouseIcon className="h-5 w-5" />}
            label="Import from Greenhouse"
            sub="Pull applicants flagged for this role"
            comingSoon
            onClick={() => {}}
          />
        </div>
      )}
      {atsModal && (
        <ImportFromAtsModal
          id={`${id}-ats-modal`}
          roleId={roleId}
          roleTitle={roleTitle}
          provider={atsModal}
          onClose={() => setAtsModal(null)}
        />
      )}
    </div>
  );
}

function MenuButton({
  id,
  icon,
  label,
  sub,
  onClick,
  accent = false,
  comingSoon = false,
}: {
  id: string;
  icon: React.ReactNode;
  label: string;
  sub: string;
  onClick: () => void;
  accent?: boolean;
  comingSoon?: boolean;
}) {
  return (
    <button
      id={id}
      type="button"
      role="menuitem"
      onClick={onClick}
      disabled={comingSoon}
      aria-disabled={comingSoon || undefined}
      className={cn(
        'flex items-start gap-3 px-3.5 py-2.5 text-left transition-colors',
        comingSoon ? 'cursor-not-allowed opacity-60' : 'hover:bg-surface',
        accent && 'bg-surface/40',
      )}
    >
      <span className="mt-0.5 shrink-0">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          <span className="min-w-0 flex-1 font-medium text-[13px] text-text-primary leading-tight">{label}</span>
          {comingSoon && (
            <span className="inline-flex shrink-0 items-center whitespace-nowrap rounded-full border border-border bg-surface px-1.5 py-0.5 font-mono text-[9px] text-text-muted uppercase leading-none tracking-[0.14em]">
              Coming soon
            </span>
          )}
        </span>
        <span className="mt-0.5 block text-[11.5px] text-text-muted leading-tight">{sub}</span>
      </span>
      {accent && <Radar strokeWidth={1.75} className="mt-1 h-3.5 w-3.5 shrink-0 text-cortex-500" />}
    </button>
  );
}
