'use client';

import { SettingsCardSkeleton } from '@/components/shell/skeletons';
import { useBillingOverview } from '@/hooks/use-services';

export function BillingTab({ id }: { id: string }) {
  const { data: overview } = useBillingOverview();

  if (!overview) {
    return <SettingsCardSkeleton id={id} rows={3} />;
  }

  const periodStart = overview.period_start
    ? new Date(overview.period_start).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
    : null;
  const periodEnd = overview.period_end
    ? new Date(overview.period_end).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
    : null;

  return (
    <div id={id} className="flex max-w-2xl flex-col gap-6">
      <header>
        <h3 className="font-display text-[22px] text-text-primary tracking-[-0.01em]">Billing</h3>
        <p className="mt-1 text-[13px] text-text-muted">
          Your plan and remaining credits. Plan changes are handled through your account contract —
          contact us for upgrades or invoicing questions.
        </p>
      </header>

      <section id={`${id}-plan`} className="rounded-[14px] border border-border bg-white p-5">
        <p className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
          Current plan
        </p>
        <p className="mt-1 font-display text-[24px] text-text-primary">{overview.plan_display_name}</p>
        <dl id={`${id}-plan-meta`} className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          {periodStart && (
            <MetaRow id={`${id}-plan-start`} label="Date of purchase" value={periodStart} />
          )}
          {periodEnd && (
            <MetaRow
              id={`${id}-plan-end`}
              label={overview.cancel_at_period_end ? 'Ends on' : 'Renews on'}
              value={periodEnd}
            />
          )}
          <MetaRow id={`${id}-plan-status`} label="Status" value={overview.subscription_status} mono />
        </dl>
      </section>

      <section id={`${id}-credits`} className="rounded-[14px] border border-border bg-white p-5">
        <p className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
          Credits remaining this period
        </p>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <CreditCard
            id={`${id}-credits-interview`}
            label="Interviews"
            used={overview.interview_used}
            total={overview.interview_total}
            topup={overview.interview_topup}
          />
          <CreditCard
            id={`${id}-credits-intake`}
            label="Intakes"
            used={overview.intake_used}
            total={overview.intake_total}
            topup={overview.intake_topup}
          />
        </div>
      </section>
    </div>
  );
}

function MetaRow({
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
      <dt className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">{label}</dt>
      <dd className={mono ? 'font-mono text-[12.5px] text-text-primary' : 'text-[13px] text-text-primary'}>
        {value}
      </dd>
    </div>
  );
}

function CreditCard({
  id,
  label,
  used,
  total,
  topup,
}: {
  id: string;
  label: string;
  used: number;
  total: number;
  topup: number;
}) {
  const remaining = total === -1 ? -1 : Math.max(0, total - used);
  const remainingDisplay = remaining === -1 ? '∞' : String(remaining);
  const totalDisplay = total === -1 ? '∞' : String(total);

  return (
    <div id={id} className="rounded-[10px] border border-border bg-surface px-3 py-3">
      <p className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">{label}</p>
      <p className="mt-1 font-display text-[20px] text-text-primary tabular-nums">
        {remainingDisplay}
        <span className="ml-1 font-sans text-[12px] text-text-muted">/ {totalDisplay}</span>
      </p>
      {topup > 0 && (
        <p className="mt-1 text-[11px] text-text-muted">+{topup} topup</p>
      )}
    </div>
  );
}
