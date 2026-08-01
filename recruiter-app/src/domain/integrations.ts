import type { IntegrationProvider, IntegrationStatus } from './enums';

export interface Integration {
  provider: IntegrationProvider;
  status: IntegrationStatus;
  label: string;
  blurb: string;
  connected_at: string | null;
  last_synced_at: string | null;
  metadata: Record<string, string | boolean>;
}

export interface ConnectResult {
  provider: IntegrationProvider;
  auth_url: string;
}
