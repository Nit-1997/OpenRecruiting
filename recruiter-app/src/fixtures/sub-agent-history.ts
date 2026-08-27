import type { SubAgentId } from '@/types';
import type { HistorySeed } from './home-history';

export const SUB_AGENT_HISTORY: Record<SubAgentId, HistorySeed[]> = {
  intake: [
    {
      role: 'user',
      text: 'Kick off a new Staff Frontend role for the Atlas team.',
      minutesAgo: 2880,
    },
    {
      role: 'agent',
      text: 'Got it — routed from home. Starting intake for Staff Frontend · Atlas.',
      minutesAgo: 2878,
    },
    {
      role: 'agent',
      text: 'Quick pass: level, comp band, must-have stack?',
      minutesAgo: 2876,
    },
    { role: 'user', text: 'IC5, 260–320 base, React + TS + perf.', minutesAgo: 2870 },
    {
      role: 'agent',
      text: 'Drafted the requisition. Opened it on the right for review.',
      minutesAgo: 2866,
    },
    { role: 'user', text: 'Tighten the impact bullet.', minutesAgo: 1440 },
    { role: 'agent', text: 'Tightened. Publish when you are ready.', minutesAgo: 1438 },
    {
      role: 'user',
      text: 'Start another one — Senior PM, Growth.',
      minutesAgo: 720,
    },
    {
      role: 'agent',
      text: 'New intake queued. Which way do you want to work this one?',
      minutesAgo: 718,
    },
  ],

  sourcing: [
    {
      role: 'user',
      text: 'Source backend staff candidates, Bay Area preferred.',
      minutesAgo: 2400,
    },
    {
      role: 'agent',
      text: 'Pulled 42 ranked matches. Top 10 on the right.',
      minutesAgo: 2398,
    },
    { role: 'user', text: 'Filter down to fintech backgrounds.', minutesAgo: 1500 },
    { role: 'agent', text: '14 remain. Sorted by recent signal.', minutesAgo: 1498 },
    {
      role: 'user',
      text: 'Draft outreach for the top 5 — include comp range.',
      minutesAgo: 700,
    },
    { role: 'agent', text: 'Drafted and sent. I will track replies.', minutesAgo: 698 },
  ],

  debrief: [
    {
      role: 'user',
      text: 'Run debrief for Atlas Staff PM — Sloane onsite.',
      minutesAgo: 2100,
    },
    {
      role: 'agent',
      text: 'Pulled all 4 scorecards. Signal splits on systems design.',
      minutesAgo: 2098,
    },
    { role: 'user', text: 'Who pushed back hardest?', minutesAgo: 1800 },
    { role: 'agent', text: 'Dan — flagged leveling on the scoping question.', minutesAgo: 1798 },
    { role: 'user', text: 'Schedule the sync, 30m.', minutesAgo: 1200 },
    { role: 'agent', text: 'Booked for 2pm PT. Packet will be ready by then.', minutesAgo: 1198 },
  ],

  brain: [
    {
      role: 'user',
      text: 'Which roles are stalling past 21 days in onsite?',
      minutesAgo: 2600,
    },
    {
      role: 'agent',
      text: '3 roles: Staff Backend, Senior Design, EM Platform. Common thread — panel availability.',
      minutesAgo: 2598,
    },
    {
      role: 'user',
      text: 'Who is my strongest sourcer this quarter?',
      minutesAgo: 1500,
    },
    {
      role: 'agent',
      text: 'Mei — 38% reply rate, 6 hires. Breakdown on the right.',
      minutesAgo: 1498,
    },
    { role: 'user', text: 'Trends on time-to-offer?', minutesAgo: 600 },
    {
      role: 'agent',
      text: 'Median down 4 days QoQ. Biggest gain: debrief turnaround.',
      minutesAgo: 598,
    },
  ],
};

export const SUB_AGENT_HISTORY_CHUNK = 4;
