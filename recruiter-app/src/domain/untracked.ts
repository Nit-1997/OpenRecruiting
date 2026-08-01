import type { UntrackedStatus } from './enums';

export interface UntrackedInterview {
  id: string;
  candidate_name: string;
  candidate_email: string;
  event_title: string;
  event_start: string;
  event_duration_minutes: number;
  interviewer_email: string;
  recording_url: string | null;
  status: UntrackedStatus;
  imported_candidate_id: string | null;
  imported_requisition_id: string | null;
  // Source-side identity — the captured candidate + the org's generic
  // (materialized) requisition that holds the candidate_round backing the
  // feedback packet. The PacketDrawer uses these to fetch the packet via
  // the standard /roles/{id}/candidates/{cid}/packet RPC without a
  // special-case route. Mock-path back-fills them from the synthetic seed.
  source_candidate_id: string;
  source_requisition_id: string;
  detected_at: string;
}
