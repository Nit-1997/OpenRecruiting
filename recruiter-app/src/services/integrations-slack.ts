import { v2Client } from '@/lib/v2-client';

const BASE = '/api/v2/integrations/slack';

export interface SlackStatus {
  connected: boolean;
  team_name: string | null;
  connected_at: string | null;
  healthy: boolean | null;
  needs_reauth: boolean | null;
  auth_state: string | null;
  token_expires_at: string | null;
  last_auth_error_code: string | null;
}

export async function getSlackStatus(): Promise<SlackStatus> {
  return v2Client.get<SlackStatus>(`${BASE}/status`);
}

export async function getSlackInstallUrl(): Promise<string> {
  const res = await v2Client.get<{ redirect_url: string }>(`${BASE}/install`);
  return res.redirect_url;
}

export async function disconnectSlack(): Promise<void> {
  await v2Client.delete(`${BASE}/disconnect`);
}
