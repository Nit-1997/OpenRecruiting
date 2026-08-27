export interface HistorySeed {
  role: 'user' | 'agent';
  text: string;
  minutesAgo: number;
}

export const HOME_HISTORY: HistorySeed[] = [
  {
    role: 'agent',
    text: 'Good morning, Taylor. Atlas interviews lead the day — want the rundown?',
    minutesAgo: 1700,
  },
  { role: 'user', text: 'Yeah, run the morning brief.', minutesAgo: 1695 },
  {
    role: 'agent',
    text: '2 onsites today, 1 debrief waiting, and the backend outreach is queued.',
    minutesAgo: 1690,
  },
  { role: 'user', text: 'Status on Atlas Staff PM?', minutesAgo: 1620 },
  {
    role: 'agent',
    text: '2 onsites this week. Sloane and Dan confirmed.',
    minutesAgo: 1615,
  },
  { role: 'user', text: 'Push Sloane to Thursday same slot.', minutesAgo: 1540 },
  { role: 'agent', text: 'Done — Sloane locked for Thu 10am PT.', minutesAgo: 1538 },
  {
    role: 'user',
    text: 'Draft outreach for the staff backend role.',
    minutesAgo: 1320,
  },
  {
    role: 'agent',
    text: 'Drafted. Want it casual or should I include the comp range?',
    minutesAgo: 1316,
  },
  { role: 'user', text: 'Include the comp range.', minutesAgo: 1190 },
  { role: 'agent', text: 'Sent to 12 in the Tier 1 queue.', minutesAgo: 1185 },
  { role: 'user', text: 'Close the IC4 iOS req — internal hire landed.', minutesAgo: 540 },
  {
    role: 'agent',
    text: 'Closed. Want me to notify the 3 active candidates?',
    minutesAgo: 535,
  },
  { role: 'user', text: 'Yes, soft decline.', minutesAgo: 520 },
  { role: 'agent', text: 'Sent. Logged outcomes in the pipeline.', minutesAgo: 515 },
  { role: 'user', text: 'Update the PM scorecard for the onsite round.', minutesAgo: 240 },
  { role: 'agent', text: 'Which question do you want swapped?', minutesAgo: 235 },
  { role: 'user', text: 'Swap the product-sense one for a systems question.', minutesAgo: 180 },
  {
    role: 'agent',
    text: 'Swapped. Scorecard saved — the panel will see it on their next prep.',
    minutesAgo: 175,
  },
  {
    role: 'user',
    text: "Remind me — who's left in the Atlas pipeline?",
    minutesAgo: 90,
  },
  {
    role: 'agent',
    text: '4 candidates: Sloane (onsite Thu), Dan (onsite Fri), Mei (debrief pending), Alex (scorecards back).',
    minutesAgo: 85,
  },
];

export const HISTORY_CHUNK = 4;
