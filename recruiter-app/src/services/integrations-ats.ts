import { v2Client } from '@/lib/v2-client';

const BASE = '/api/v2/integrations/ats';

export interface AtsImportSummary {
  created: number;
  updated: number;
  flagged: number;
  skipped_closed: number;
  skipped_other: number;
  errors: number;
  sync_started: boolean;
}

export interface AtsStatus {
  connected: boolean;
  provider: string | null;
  status: string | null;
  connected_at: string | null;
  connected_by_name: string | null;
  /** Present on the POST /connections response (connect-time auto-import). */
  import_summary?: AtsImportSummary | null;
}

export interface AtsRequisitionSync {
  linked: boolean;
  provider: string | null;
  ats_status: string | null;
  ats_dirty: boolean;
  ats_deleted: boolean;
  pending_changes: Record<string, unknown> | null;
}

/** Verbatim integrationDetails payload from the knit-auth onFinish event. */
export interface KnitIntegrationDetails {
  integrationId: string;
  appId?: string;
  categoryId?: string;
  originOrgId?: string;
  success: boolean;
}

export async function getAtsSessionToken(): Promise<string> {
  const res = await v2Client.post<{ token: string }>(`${BASE}/session`, {});
  return res.token;
}

export async function completeAtsConnection(details: KnitIntegrationDetails): Promise<AtsStatus> {
  return v2Client.post<AtsStatus>(`${BASE}/connections`, details);
}

export async function getAtsStatus(): Promise<AtsStatus> {
  return v2Client.get<AtsStatus>(`${BASE}/status`);
}

export async function disconnectAts(): Promise<void> {
  await v2Client.delete(`${BASE}/connection`);
}

export async function runAtsImport(includeClosed = false): Promise<AtsImportSummary> {
  return v2Client.post<AtsImportSummary>(`${BASE}/import?include_closed=${includeClosed}`, {});
}

export async function getRequisitionAtsSync(requisitionId: string): Promise<AtsRequisitionSync> {
  return v2Client.get<AtsRequisitionSync>(`${BASE}/requisitions/${requisitionId}/sync`);
}

export async function applyAtsUpdate(requisitionId: string): Promise<void> {
  await v2Client.post(`${BASE}/requisitions/${requisitionId}/apply-update`, {});
}

export async function dismissAtsUpdate(requisitionId: string): Promise<void> {
  await v2Client.post(`${BASE}/requisitions/${requisitionId}/dismiss-update`, {});
}
