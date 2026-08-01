export type UntrackedInterviewStatus = 'available' | 'imported' | 'failed';

export interface UntrackedInterview {
  id: string;
  candidate_name: string;
  candidate_email: string;
  event_title: string;
  event_start: string;
  interviewer_email: string;
  status: UntrackedInterviewStatus;
}

export const UNTRACKED_INTERVIEWS: UntrackedInterview[] = [
  {
    id: 'ut-1',
    candidate_name: 'Jordan Lee',
    candidate_email: 'jordan.lee@example.com',
    event_title: 'Loop kickoff — TBD role',
    event_start: '2026-04-22T14:15:00Z',
    interviewer_email: 'priya.patel@example.com',
    status: 'available',
  },
  {
    id: 'ut-2',
    candidate_name: 'Rhea Gupta',
    candidate_email: 'rhea.gupta@example.com',
    event_title: 'External interview (unmatched req)',
    event_start: '2026-04-19T17:00:00Z',
    interviewer_email: 'alex.kim@example.com',
    status: 'available',
  },
  {
    id: 'ut-3',
    candidate_name: 'Theo Martinez',
    candidate_email: 'theo.martinez@example.com',
    event_title: 'Portfolio review — design org',
    event_start: '2026-04-21T20:30:00Z',
    interviewer_email: 'miranda.ross@example.com',
    status: 'imported',
  },
  {
    id: 'ut-4',
    candidate_name: 'Ada Okafor',
    candidate_email: 'ada.okafor@example.com',
    event_title: 'Screen — unmatched calendar event',
    event_start: '2026-04-20T15:45:00Z',
    interviewer_email: 'jordan.lee@example.com',
    status: 'failed',
  },
];
