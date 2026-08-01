import type { BillingOverview } from '@/domain';
import { v2Client } from '@/lib/v2-client';

export async function getOverview(): Promise<BillingOverview> {
  return v2Client.get<BillingOverview>('/api/v2/billing/overview');
}
