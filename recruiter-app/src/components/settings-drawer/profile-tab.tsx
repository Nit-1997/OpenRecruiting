'use client';

import { useProfile, useTeam } from '@/hooks/use-services';

export function ProfileTab({ id }: { id: string }) {
  const { data: profile } = useProfile();
  const { data: team } = useTeam();

  if (!profile) {
    return (
      <div id={id} className="text-[13px] text-text-muted">
        Loading profile…
      </div>
    );
  }

  return (
    <div id={id} className="flex max-w-lg flex-col gap-6">
      <header>
        <h3 className="font-display text-[22px] text-text-primary tracking-[-0.01em]">Profile</h3>
        <p className="mt-1 text-[13px] text-text-muted">Your account on OpenRecruiting.</p>
      </header>

      <section
        id={`${id}-identity`}
        className="flex flex-col gap-3 rounded-[14px] border border-border bg-white p-5"
      >
        <FieldRow id={`${id}-name`} label="Name" value={profile.name} />
        <FieldRow id={`${id}-email`} label="Email" value={profile.email} mono />
        <FieldRow
          id={`${id}-org`}
          label="Organization"
          value={team?.organization_name ?? '—'}
        />
      </section>
    </div>
  );
}

function FieldRow({
  id,
  label,
  value,
  mono,
}: {
  id: string;
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div id={id} className="flex flex-col gap-0.5">
      <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
        {label}
      </span>
      <span
        className={
          mono ? 'font-mono text-[12.5px] text-text-primary' : 'text-[13px] text-text-primary'
        }
      >
        {value}
      </span>
    </div>
  );
}
