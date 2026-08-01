export type SubscriptionStatus = 'active' | 'cancelled' | 'none';

export interface BillingOverview {
  plan_name: string;
  plan_display_name: string;
  subscription_status: SubscriptionStatus;
  period_start: string | null;
  period_end: string | null;
  cancel_at_period_end: boolean;
  intake_total: number;       // -1 = unlimited
  intake_used: number;
  intake_topup: number;
  interview_total: number;    // -1 = unlimited
  interview_used: number;
  interview_topup: number;
}
