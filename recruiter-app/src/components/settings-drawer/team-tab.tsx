'use client';

import { useState } from 'react';
import { SettingsCardSkeleton } from '@/components/shell/skeletons';
import { useTeam } from '@/hooks/use-services';
import { cn, pickAvatarFg } from '@/lib/utils';
import { team as teamSvc } from '@/services';
import { ServiceError } from '@/services/service-error';

export function TeamTab({ id }: { id: string }) {
  const { data: team } = useTeam();
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [cancellingId, setCancellingId] = useState<string | null>(null);
  const [confirmRemoveId, setConfirmRemoveId] = useState<string | null>(null);

  if (!team) {
    return <SettingsCardSkeleton id={id} rows={4} />;
  }

  const invite = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await teamSvc.invite(email, 'recruiter');
      setEmail('');
    } catch (err) {
      setError(err instanceof ServiceError ? err.message : 'Could not send invite');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div id={id} className="flex max-w-3xl flex-col gap-6">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h3 className="font-display text-[22px] text-text-primary tracking-[-0.01em]">Team</h3>
          <p className="mt-1 text-[13px] text-text-muted">
            {team.seat_usage.total === -1
              ? `${team.members.length} members · unlimited seats`
              : `${team.members.length} of ${team.seat_usage.total} seats in use`}
          </p>
        </div>
        <div className="rounded-[10px] bg-surface px-3 py-1.5 font-mono text-[11px] text-text-primary tabular-nums">
          {team.seat_usage.used} / {team.seat_usage.total === -1 ? '∞' : team.seat_usage.total}
        </div>
      </header>

      <section className="rounded-[14px] border border-border bg-white">
        <header className="flex items-center justify-between border-border border-b bg-surface px-4 py-2.5 font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
          <span>Members</span>
          <span>{team.members.length}</span>
        </header>
        <ul className="divide-y divide-border">
          {team.members.map((m) => (
            <li
              key={m.id}
              id={`${id}-member-${m.id}`}
              className="flex items-center gap-3 px-4 py-3"
            >
              <div
                aria-hidden
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full font-mono text-[11px]"
                style={{ background: m.avatar_color, color: pickAvatarFg(m.avatar_color) }}
              >
                {m.avatar_initials}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-[13.5px] text-text-primary">{m.name}</p>
                <p className="truncate text-[12px] text-text-muted">{m.email}</p>
              </div>
              <span
                id={`${id}-member-${m.id}-role`}
                className="rounded-[8px] border border-border bg-surface px-2 py-1 font-mono text-[11px] text-text-muted"
              >
                {m.role}
              </span>
              {m.role !== 'owner' && (
                confirmRemoveId === m.id ? (
                  <div className="flex items-center gap-1.5">
                    <button
                      id={`${id}-member-${m.id}-confirm-remove`}
                      type="button"
                      onClick={async () => {
                        await teamSvc
                          .remove(m.id)
                          .catch((err) =>
                            setError(err instanceof ServiceError ? err.message : 'Could not remove'),
                          );
                        setConfirmRemoveId(null);
                      }}
                      className="rounded-full border border-[#B91C1C] bg-white px-2 py-1 text-[11px] text-[#B91C1C]"
                    >
                      Remove
                    </button>
                    <button
                      id={`${id}-member-${m.id}-cancel-remove`}
                      type="button"
                      onClick={() => setConfirmRemoveId(null)}
                      className="rounded-full border border-border bg-white px-2 py-1 text-[11px] text-text-muted hover:border-text-primary hover:text-text-primary"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    id={`${id}-member-${m.id}-remove`}
                    type="button"
                    onClick={() => setConfirmRemoveId(m.id)}
                    className="rounded-full border border-border bg-white px-2 py-1 text-[11px] text-text-muted hover:border-[#B91C1C] hover:text-[#B91C1C]"
                  >
                    Remove
                  </button>
                )
              )}
            </li>
          ))}
        </ul>
      </section>

      {team.pending_invites.length > 0 && (
        <section className="rounded-[14px] border border-border bg-white">
          <header className="flex items-center justify-between border-border border-b bg-surface px-4 py-2.5 font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
            <span>Pending invites</span>
            <span>{team.pending_invites.length}</span>
          </header>
          <ul className="divide-y divide-border">
            {team.pending_invites.map((inv) => (
              <li
                key={inv.id}
                id={`${id}-invite-${inv.id}`}
                className="flex items-center gap-3 px-4 py-3"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium text-[13.5px] text-text-primary">
                    {inv.email}
                  </p>
                  <p className="truncate text-[12px] text-text-muted">
                    Expires {new Date(inv.expires_at).toLocaleDateString()}
                    {inv.invited_by_name ? ` · invited by ${inv.invited_by_name}` : ''}
                  </p>
                </div>
                <button
                  id={`${id}-invite-${inv.id}-cancel`}
                  type="button"
                  disabled={cancellingId === inv.id}
                  onClick={async () => {
                    setCancellingId(inv.id);
                    setError(null);
                    try {
                      await teamSvc.cancelInvite(inv.id);
                    } catch (err) {
                      setError(err instanceof ServiceError ? err.message : 'Could not cancel invite');
                    } finally {
                      setCancellingId(null);
                    }
                  }}
                  className="rounded-full border border-border bg-white px-2 py-1 text-[11px] text-text-muted hover:border-[#B91C1C] hover:text-[#B91C1C] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {cancellingId === inv.id ? 'Cancelling…' : 'Cancel'}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <form
        id={`${id}-invite-form`}
        onSubmit={invite}
        className="flex flex-col gap-3 rounded-[14px] border border-border border-dashed bg-white p-5"
      >
        <p className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
          Invite someone
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-1 flex-col gap-1">
            <span className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
              Email
            </span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="teammate@example.com"
              className="rounded-[10px] border border-border bg-white px-3 py-2 text-[13px] text-text-primary placeholder:text-text-muted focus:border-text-primary focus:outline-none"
            />
          </label>
          <button
            type="submit"
            disabled={!email.trim() || busy}
            className={cn(
              'rounded-full px-3.5 py-2 text-[13px] font-medium transition-colors',
              email.trim() && !busy
                ? 'border border-text-primary bg-text-primary text-white hover:bg-[#222]'
                : 'cursor-not-allowed border border-border bg-surface text-text-faint',
            )}
          >
            {busy ? 'Sending…' : 'Send invite'}
          </button>
        </div>
        {error && <p className="text-[12.5px] text-[#B91C1C]">{error}</p>}
      </form>
    </div>
  );
}
