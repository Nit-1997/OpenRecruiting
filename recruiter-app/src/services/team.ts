import type { Invite, OrgRole, TeamMember, TeamOverview } from '@/domain';
import { v2Client } from '@/lib/v2-client';
import { emit } from './events';

const BASE = '/api/v2/team';

interface ApiTeamOverview {
  organization_id: string;
  organization_name: string;
  members: {
    id: string;
    user_id: string;
    name: string;
    email: string;
    role: string;
    avatar_initials: string;
    avatar_color: string;
    joined_at: string;
    last_active_at: string | null;
  }[];
  pending_invites: {
    id: string;
    email: string;
    role: string;
    invited_by_id: string | null;
    invited_by_name: string | null;
    created_at: string;
    expires_at: string;
    status: string;
  }[];
  seat_usage: { used: number; total: number };
}

function toTeamOverview(raw: ApiTeamOverview): TeamOverview {
  return {
    organization_id: raw.organization_id,
    organization_name: raw.organization_name,
    members: raw.members.map(
      (m): TeamMember => ({
        id: m.id,
        user_id: m.user_id,
        name: m.name,
        email: m.email,
        role: m.role as OrgRole,
        avatar_initials: m.avatar_initials,
        avatar_color: m.avatar_color,
        joined_at: m.joined_at,
        last_active_at: m.last_active_at,
      }),
    ),
    pending_invites: raw.pending_invites.map(
      (i): Invite => ({
        id: i.id,
        email: i.email,
        role: i.role as OrgRole,
        invited_by_id: i.invited_by_id ?? '',
        invited_by_name: i.invited_by_name ?? '',
        created_at: i.created_at,
        expires_at: i.expires_at,
        status: i.status as Invite['status'],
      }),
    ),
    seat_usage: raw.seat_usage,
  };
}

export async function get(): Promise<TeamOverview> {
  const raw = await v2Client.get<ApiTeamOverview>(BASE);
  return toTeamOverview(raw);
}

export async function invite(email: string, role: OrgRole): Promise<Invite> {
  const raw = await v2Client.post<ApiTeamOverview['pending_invites'][0]>(`${BASE}/invite`, {
    email,
    role,
  });
  emit('team:updated');
  return {
    id: raw.id,
    email: raw.email,
    role: raw.role as OrgRole,
    invited_by_id: raw.invited_by_id ?? '',
    invited_by_name: raw.invited_by_name ?? '',
    created_at: raw.created_at,
    expires_at: raw.expires_at,
    status: raw.status as Invite['status'],
  };
}

export async function cancelInvite(inviteId: string): Promise<void> {
  await v2Client.delete(`${BASE}/invites/${inviteId}`);
  emit('team:updated');
}

export async function acceptInvite(): Promise<void> {
  await v2Client.post(`${BASE}/accept-invite`, {});
}

export async function remove(memberId: string): Promise<void> {
  await v2Client.delete(`${BASE}/members/${memberId}`);
  emit('team:updated');
}
