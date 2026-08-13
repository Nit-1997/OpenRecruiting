// The organization holds one credit budget that every member draws from.
// There are no plans or subscriptions — an admin sets the cap from the admin
// portal. A total of -1 means unlimited.
export interface BillingOverview {
  intake_total: number;
  intake_used: number;
  interview_total: number;
  interview_used: number;
}
