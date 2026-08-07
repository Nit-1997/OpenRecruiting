'use client';

import type { NotificationPreferences } from '@/domain';
import { useNotificationPrefs } from '@/hooks/use-services';
import { cn } from '@/lib/utils';
import { profile as profileSvc } from '@/services';

type PrefKey = keyof Omit<NotificationPreferences, 'user_id'>;

const EMAIL_KEYS: Array<{ key: PrefKey; label: string; blurb: string }> = [
  {
    key: 'email_feedback_requests',
    label: 'Feedback requests',
    blurb: 'Email me when a debrief is assigned to me.',
  },
  {
    key: 'email_interview_reminders',
    label: 'Interview reminders',
    blurb: '30 minutes before each scheduled interview.',
  },
  {
    key: 'email_weekly_digest',
    label: 'Weekly digest',
    blurb: 'Monday morning recap across all your roles.',
  },
];

export function NotificationsTab({ id }: { id: string }) {
  const { data: prefs, error } = useNotificationPrefs();

  if (error) {
    return (
      <div id={id} className="text-[13px] text-text-muted">
        Notification preferences aren’t available yet.
      </div>
    );
  }

  if (!prefs) {
    return (
      <div id={id} className="text-[13px] text-text-muted">
        Loading preferences…
      </div>
    );
  }

  return (
    <div id={id} className="flex max-w-2xl flex-col gap-6">
      <header>
        <h3 className="font-display text-[22px] text-text-primary tracking-[-0.01em]">
          Notifications
        </h3>
        <p className="mt-1 text-[13px] text-text-muted">Where should OpenRecruiting reach you?</p>
      </header>

      <Channel id={`${id}-email`} title="Email" rows={EMAIL_KEYS} prefs={prefs} />
    </div>
  );
}

function Channel({
  id,
  title,
  rows,
  prefs,
}: {
  id: string;
  title: string;
  rows: Array<{ key: PrefKey; label: string; blurb: string }>;
  prefs: NotificationPreferences;
}) {
  return (
    <section id={id} className="rounded-[14px] border border-border bg-white">
      <header className="border-border border-b bg-surface px-4 py-2.5 font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
        {title}
      </header>
      <ul className="divide-y divide-border">
        {rows.map((row) => (
          <li key={row.key} id={`${id}-${row.key}`} className="flex items-center gap-3 px-4 py-3">
            <div className="min-w-0 flex-1">
              <p className="font-medium text-[13.5px] text-text-primary">{row.label}</p>
              <p className="text-[12.5px] text-text-muted">{row.blurb}</p>
            </div>
            <Toggle
              id={`${id}-${row.key}-toggle`}
              on={Boolean(prefs[row.key])}
              onChange={(next) => {
                profileSvc.updateNotificationPrefs({ [row.key]: next }).catch(() => {});
              }}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}

function Toggle({
  id,
  on,
  onChange,
}: {
  id: string;
  on: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => onChange(!on)}
      className={cn(
        'relative h-6 w-10 shrink-0 rounded-full transition-colors',
        on ? 'bg-text-primary' : 'bg-surface',
      )}
    >
      <span
        aria-hidden
        className={cn(
          'absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow-[0_1px_3px_rgba(0,0,0,0.2)] transition-transform',
          on && 'translate-x-4',
        )}
      />
    </button>
  );
}
