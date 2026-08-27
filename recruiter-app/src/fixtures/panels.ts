export type PanelMode = 'video' | 'phone' | 'in-person';

export interface PanelInterviewer {
  id: string;
  name: string;
  role: string;
  avatar: string;
  color: string;
}

export interface PanelSlot {
  id: string;
  candidateId: string;
  candidateName: string;
  candidateAvatar: string;
  candidateColor: string;
  when: string;
  duration: number;
  interviewerId: string;
  mode: PanelMode;
  status: 'confirmed' | 'pending';
}

export interface Panel {
  roleId: string;
  roundId: string;
  roundTitle: string;
  durationMin: number;
  interviewers: PanelInterviewer[];
  slots: PanelSlot[];
}

const PM_SFO_INTERVIEWERS: PanelInterviewer[] = [
  { id: 'i1', name: 'Sana Reyes', role: 'Senior PM', avatar: 'SR', color: '#EADFD4' },
  { id: 'i2', name: 'Anand Patel', role: 'Tech lead', avatar: 'AP', color: '#DDE8F6' },
  { id: 'i3', name: 'David Woo', role: 'Hiring manager', avatar: 'DW', color: '#D8EFE3' },
  { id: 'i4', name: 'Marcus Chen', role: 'EM · Values', avatar: 'MC', color: '#E9DFF5' },
];

function key(roleId: string, roundId: string): string {
  return `${roleId}::${roundId}`;
}

export const PANELS: Record<string, Panel> = {
  [key('pm-sfo', 'rs')]: {
    roleId: 'pm-sfo',
    roundId: 'rs',
    roundTitle: 'Recruiter screen',
    durationMin: 30,
    interviewers: [PM_SFO_INTERVIEWERS[0] as PanelInterviewer].filter(
      Boolean,
    ) as PanelInterviewer[],
    slots: [
      {
        id: 'rs-s1',
        candidateId: 'c10',
        candidateName: 'Jon Park',
        candidateAvatar: 'JP',
        candidateColor: '#F4E9D8',
        when: 'Mon · 3:00 PM',
        duration: 30,
        interviewerId: 'i1',
        mode: 'phone',
        status: 'confirmed',
      },
    ],
  },
  [key('pm-sfo', 'hm')]: {
    roleId: 'pm-sfo',
    roundId: 'hm',
    roundTitle: 'Hiring Manager Interview',
    durationMin: 45,
    interviewers: [PM_SFO_INTERVIEWERS[2] as PanelInterviewer].filter(
      Boolean,
    ) as PanelInterviewer[],
    slots: [
      {
        id: 'hm-s1',
        candidateId: 'c2',
        candidateName: 'Marcus Chen',
        candidateAvatar: 'MC',
        candidateColor: '#D8EFE3',
        when: 'Tue · 2:00 PM',
        duration: 45,
        interviewerId: 'i3',
        mode: 'video',
        status: 'pending',
      },
      {
        id: 'hm-s2',
        candidateId: 'c13',
        candidateName: 'Yuki Tanaka',
        candidateAvatar: 'YT',
        candidateColor: '#EADFD4',
        when: 'Thu · 10:30 AM',
        duration: 45,
        interviewerId: 'i3',
        mode: 'video',
        status: 'confirmed',
      },
    ],
  },
  [key('pm-sfo', 'ps')]: {
    roleId: 'pm-sfo',
    roundId: 'ps',
    roundTitle: 'Product Sense & Strategy',
    durationMin: 60,
    interviewers: PM_SFO_INTERVIEWERS.slice(0, 3),
    slots: [
      {
        id: 'ps-s1',
        candidateId: 'c1',
        candidateName: 'Sloane Natarajan',
        candidateAvatar: 'PN',
        candidateColor: '#EADFD4',
        when: 'Today · 2:30 PM',
        duration: 45,
        interviewerId: 'i1',
        mode: 'video',
        status: 'confirmed',
      },
      {
        id: 'ps-s2',
        candidateId: 'c7',
        candidateName: 'Eleanor Whitfield',
        candidateAvatar: 'EW',
        candidateColor: '#EADFD4',
        when: 'Tue · 11:00 AM',
        duration: 60,
        interviewerId: 'i2',
        mode: 'in-person',
        status: 'confirmed',
      },
    ],
  },
  [key('pm-sfo', 'cv')]: {
    roleId: 'pm-sfo',
    roundId: 'cv',
    roundTitle: 'Culture & Values Interview',
    durationMin: 45,
    interviewers: [PM_SFO_INTERVIEWERS[3] as PanelInterviewer].filter(
      Boolean,
    ) as PanelInterviewer[],
    slots: [
      {
        id: 'cv-s1',
        candidateId: 'c4',
        candidateName: 'David Kim',
        candidateAvatar: 'DK',
        candidateColor: '#F6E4DA',
        when: 'Wed · 10:00 AM',
        duration: 45,
        interviewerId: 'i4',
        mode: 'video',
        status: 'confirmed',
      },
    ],
  },
};

export function getPanel(roleId: string, roundId: string): Panel | null {
  return PANELS[key(roleId, roundId)] ?? null;
}

export function getPanelOrDefault(roleId: string, roundId: string, roundTitle: string): Panel {
  const existing = getPanel(roleId, roundId);
  if (existing) return existing;
  return {
    roleId,
    roundId,
    roundTitle,
    durationMin: 45,
    interviewers: [
      {
        id: 'def-i1',
        name: 'David Woo',
        role: 'Hiring manager',
        avatar: 'DW',
        color: '#D8EFE3',
      },
    ],
    slots: [],
  };
}
