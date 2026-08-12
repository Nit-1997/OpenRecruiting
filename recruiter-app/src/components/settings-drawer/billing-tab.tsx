'use client';

import { SettingsCardSkeleton } from '@/components/shell/skeletons';
import { useBillingOverview } from '@/hooks/use-services';

export function BillingTab({ id }: { id: string }) {
  const { data: overview } = useBillingOverview();

  if (!overview) {
    return <SettingsCardSkeleton id={id} rows={3} />;
  }

  return (
    <div id={id} className="flex max-w-2xl flex-col gap-6">
      <header>
        <h3 className="font-display text-[22px] text-text-primary tracking-[-0.01em]">
          Credit budget
        </h3>
        <p className="mt-1 text-[13px] text-text-muted">
          Your organisation&apos;s credits, shared by everyone on the team. Nothing is charged here
          — an administrator sets the budget from the admin portal, so contact them for more.
        </p>
      </header>

      <section id={`${id}-credits`} className="rounded-[14px] border border-border bg-white p-5">
        <p className="font-mono text-[10px] text-text-faint uppercase tracking-[0.14em]">
          Credits remaining
        </p>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <CreditMeter
            id={`${id}-credits-interview`}
            label="Interviews"
            used={overview.interview_used}
            total={overview.interview_total}
            topup={overview.interview_topup}
          />
          <CreditMeter
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

function CreditMeter({
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
      {topup > 0 && <p className="mt-1 text-[11px] text-text-muted">+{topup} topup</p>}
    </div>
  );
}
