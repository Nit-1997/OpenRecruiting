'use client';

import { ChevronLeft, MapPin } from 'lucide-react';
import Link from 'next/link';
import { getCandidatesForReq } from '@/fixtures/candidates';
import { findRoleById, type RoleFixture } from '@/fixtures/roles';
import { cn, pickAvatarFg } from '@/lib/utils';
interface RowDetailProps {
  id: string;
  roleId: string;
}

export function RowDetail({ id, roleId }: RowDetailProps) {
  const role = findRoleById(roleId);

  if (!role) {
    return (
      <div id={id} className="pt-10 pb-8">
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

  return <RoleDetailBody id={id} role={role} />;
}

function RoleDetailBody({ id, role }: { id: string; role: RoleFixture }) {
  const candidates = getCandidatesForReq(role.id);
  const rounds = [
    { id: 'rs', n: 1, title: 'Resume screen + recruiter', dur: '30 min' },
    { id: 'hm', n: 2, title: 'Hiring manager interview', dur: '45 min' },
    { id: 'ps', n: 3, title: 'Product sense & strategy panel', dur: '60 min' },
    { id: 'cv', n: 4, title: 'Culture & values interview', dur: '45 min' },
  ];

  return (
    <div id={id} className="pt-10 pb-8">
      <nav
        id={`${id}-breadcrumb`}
        aria-label="Breadcrumb"
        className="mb-3 flex items-center gap-1 font-mono text-[10.5px] text-text-faint uppercase tracking-[0.14em]"
      >
        <Link
          id={`${id}-breadcrumb-roles`}
          href="/view/roles"
          className="text-text-muted transition-colors hover:text-text-primary"
        >
          Roles
        </Link>
        <span aria-hidden>›</span>
        <span id={`${id}-breadcrumb-current`} className="text-text-primary">
          {role.title}
        </span>
      </nav>

      <header
        id={`${id}-header`}
        className="mb-8 flex flex-wrap items-end justify-between gap-3 border-border border-b pb-5"
      >
        <div id={`${id}-header-text`} className="min-w-0">
          <h1
            id={`${id}-title`}
            className="font-display text-[34px] text-text-primary leading-[1.1] tracking-[-0.01em]"
          >
            {role.title}
          </h1>
          <div
            id={`${id}-meta`}
            className="mt-2 flex flex-wrap items-center gap-3 text-[13px] text-text-muted"
          >
            <span className="flex items-center gap-1">
              <MapPin strokeWidth={1.75} className="h-3.5 w-3.5" />
              {role.loc}
            </span>
            <span>·</span>
            <span>{role.dept}</span>
            <span>·</span>
            <span>Owned by {role.owner}</span>
          </div>
        </div>
        <span
          id={`${id}-status`}
          className={cn(
            'inline-flex items-center gap-2 rounded-full border px-3 py-1 font-mono text-[10.5px] uppercase tracking-[0.14em]',
            role.status === 'live'
              ? 'border-[#A7F3D0] bg-[#ECFDF5] text-[#047857]'
              : role.status === 'paused'
                ? 'border-[#FDE68A] bg-[#FFFBEB] text-[#B45309]'
                : 'border-border bg-surface text-text-secondary',
          )}
        >
          <span
            id={`${id}-status-dot`}
            aria-hidden
            className={cn(
              'h-1.5 w-1.5 rounded-full',
              role.status === 'live'
                ? 'bg-[#10B981]'
                : role.status === 'paused'
                  ? 'bg-[#F59E0B]'
                  : 'bg-text-muted',
            )}
          />
          {role.status}
        </span>
      </header>

      <div
        id={`${id}-sections`}
        className="grid gap-8 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]"
      >
        <section id={`${id}-pipeline`} aria-label="Pipeline">
          <h2
            id={`${id}-pipeline-title`}
            className="mb-3 font-display text-[20px] text-text-primary tracking-[-0.01em]"
          >
            Pipeline
          </h2>
          <p id={`${id}-pipeline-sub`} className="mb-4 text-[13px] text-text-muted">
            {role.pipeline}
          </p>
          <ol
            id={`${id}-rounds`}
            className="divide-y divide-border rounded-[14px] border border-border bg-white"
          >
            {rounds.map((r) => (
              <li
                key={r.id}
                id={`${id}-round-${r.id}`}
                className="flex items-center gap-3 px-4 py-3"
              >
                <span
                  id={`${id}-round-${r.id}-n`}
                  className="flex h-7 w-7 items-center justify-center rounded-full bg-surface font-mono text-[11px] text-text-primary"
                >
                  {r.n}
                </span>
                <span
                  id={`${id}-round-${r.id}-title`}
                  className="flex-1 text-[13.5px] text-text-primary"
                >
                  {r.title}
                </span>
                <span
                  id={`${id}-round-${r.id}-dur`}
                  className="font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]"
                >
                  {r.dur}
                </span>
              </li>
            ))}
          </ol>
        </section>

        <section id={`${id}-candidates`} aria-label="Candidates">
          <h2
            id={`${id}-candidates-title`}
            className="mb-3 font-display text-[20px] text-text-primary tracking-[-0.01em]"
          >
            Candidates
          </h2>
          <p id={`${id}-candidates-sub`} className="mb-4 text-[13px] text-text-muted">
            {candidates.length} in the pipeline for {role.title}.
          </p>
          <ul
            id={`${id}-candidate-list`}
            className="divide-y divide-border rounded-[14px] border border-border bg-white"
          >
            {candidates.slice(0, 6).map((c) => (
              <li
                key={c.id}
                id={`${id}-candidate-${c.id}`}
                className="flex items-center gap-3 px-4 py-3"
              >
                <span
                  id={`${id}-candidate-${c.id}-avatar`}
                  aria-hidden
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full font-mono text-[11px] text-text-primary"
                  style={{ background: c.color, color: pickAvatarFg(c.color) }}
                >
                  {c.avatar}
                </span>
                <div className="min-w-0 flex-1">
                  <div
                    id={`${id}-candidate-${c.id}-name`}
                    className="truncate font-medium text-[13.5px] text-text-primary"
                  >
                    {c.name}
                  </div>
                  <div
                    id={`${id}-candidate-${c.id}-stage`}
                    className="mt-0.5 truncate text-[12px] text-text-muted"
                  >
                    {c.stage}
                  </div>
                </div>
                <span
                  id={`${id}-candidate-${c.id}-flag`}
                  className="font-mono text-[10.5px] text-text-muted uppercase tracking-[0.14em]"
                >
                  {c.flag}
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section id={`${id}-scorecard`} aria-label="Scorecard" className="lg:col-span-2">
          <h2
            id={`${id}-scorecard-title`}
            className="mb-3 font-display text-[20px] text-text-primary tracking-[-0.01em]"
          >
            Scorecard
          </h2>
          <div
            id={`${id}-scorecard-body`}
            className="rounded-[14px] border border-border bg-white p-5 text-[13px] text-text-secondary leading-[1.55]"
          >
            Must-have: {role.must_have.join(' · ')}
            <br />
            Nice-to-have: {role.nice_to_have.join(' · ') || '—'}
          </div>
        </section>
      </div>
    </div>
  );
}
