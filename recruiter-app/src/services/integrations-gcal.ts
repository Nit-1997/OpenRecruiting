import { v2Client } from '@/lib/v2-client';

const BASE = '/api/v2/integrations/google-calendar';

export interface GcalStatus {
  connected: boolean;
  email: string | null;
  connected_at: string | null;
  calendar_watch_enabled: boolean;
  auto_join_untracked: boolean;
}

export async function getGcalStatus(): Promise<GcalStatus> {
  return v2Client.get<GcalStatus>(`${BASE}/status`);
}

export async function getGcalInstallUrl(): Promise<string> {
  const res = await v2Client.get<{ redirect_url: string }>(`${BASE}/install`);
  return res.redirect_url;
}

export async function disconnectGcal(): Promise<void> {
  await v2Client.delete(`${BASE}/disconnect`);
}

export async function toggleCalendarWatch(enabled: boolean): Promise<void> {
  await v2Client.patch(`${BASE}/calendar-watch`, { enabled });
}

export async function toggleAutoJoin(enabled: boolean): Promise<void> {
  await v2Client.patch(`${BASE}/auto-join-untracked`, { enabled });
}
