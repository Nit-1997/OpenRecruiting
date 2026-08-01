import type { ActivityEventType } from './enums';

export interface ActivityEvent {
  id: string;
  type: ActivityEventType;
  title: string;
  description: string;
  actor_name: string;
  requisition_id: string | null;
  candidate_id: string | null;
  created_at: string;
}
