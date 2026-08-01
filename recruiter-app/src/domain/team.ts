import type { OrgRole } from './enums';

export interface TeamMember {
  id: string;
  user_id: string;
  name: string;
  email: string;
  role: OrgRole;
  avatar_initials: string;
  avatar_color: string;
  joined_at: string;
  last_active_at: string | null;
}

export type InviteStatus = 'pending' | 'accepted' | 'expired' | 'cancelled';

export interface Invite {
  id: string;
  email: string;
  role: OrgRole;
  invited_by_id: string;
  invited_by_name: string;
  created_at: string;
  expires_at: string;
  status: InviteStatus;
}

export interface TeamOverview {
  organization_id: string;
  organization_name: string;
  members: TeamMember[];
  pending_invites: Invite[];
  seat_usage: { used: number; total: number };
}
