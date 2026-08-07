export interface ClaudeIntegrationFixture {
  connected: boolean;
  workspace: string;
  endpoint: string;
  connected_at: string;
}

export interface AvailableIntegrationFixture {
  id: string;
  name: string;
  blurb: string;
  iconKey: 'greenhouse' | 'lever' | 'ashby';
  accent: string;
}

export interface WorkspacePreferencesFixture {
  timezone: string;
}

export const COMMON_TIMEZONES = [
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Anchorage',
  'America/Toronto',
  'America/Vancouver',
  'Pacific/Honolulu',
  'Europe/London',
  'Europe/Paris',
  'Europe/Berlin',
  'Europe/Amsterdam',
  'Europe/Dublin',
  'Asia/Kolkata',
  'Asia/Shanghai',
  'Asia/Tokyo',
  'Asia/Singapore',
  'Australia/Sydney',
  'Australia/Melbourne',
  'Pacific/Auckland',
] as const;

export const INTEGRATIONS = {
  claude: {
    connected: false,
    workspace: '',
    endpoint: 'http://localhost:8020/mcp',
    connected_at: '',
  } as ClaudeIntegrationFixture,
  available: [
    {
      id: 'ashby',
      name: 'Ashby',
      blurb: 'Import roles and candidate pipelines.',
      iconKey: 'ashby',
      accent: '#111111',
    },
    {
      id: 'greenhouse',
      name: 'Greenhouse',
      blurb: 'Sync requisitions and candidates.',
      iconKey: 'greenhouse',
      accent: '#2F9E5F',
    },
    {
      id: 'lever',
      name: 'Lever',
      blurb: 'Pull pipelines and scorecards.',
      iconKey: 'lever',
      accent: '#5D5FEF',
    },
  ] as AvailableIntegrationFixture[],
};

export const WORKSPACE_PREFERENCES: WorkspacePreferencesFixture = {
  timezone: 'America/Los_Angeles',
};

export function findAvailableIntegration(id: string): AvailableIntegrationFixture | undefined {
  return INTEGRATIONS.available.find((i) => i.id === id);
}
