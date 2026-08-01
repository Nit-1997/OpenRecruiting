import type { CortexMessageBlock } from '@/types/sub-agent';

export type CortexInsightKind = 'why_losing' | 'best_candidate' | 'silver_medalists';

export interface CortexTrailStep {
  num: string;
  body: string;
}

export interface CortexStatCard {
  title: string;
  rows: Array<{ label: string; value: string }>;
}

export interface CortexInsightMessage {
  /** Short label shown above the message body. */
  who: string;
  blocks: CortexMessageBlock[];
  chips?: Array<{ label: string; value: string; primary?: boolean }>;
}

// ---- Visual analysis artifact (why-losing split pattern) ----

export type CortexPanelistProbe = 'execution' | 'strategy';

export interface CortexPanelistMixViz {
  kind: 'panelist_mix';
  panelists: Array<{ label: string; probe: CortexPanelistProbe }>;
  executionLabel: string;
  strategyLabel: string;
}

export interface CortexSplitBarViz {
  kind: 'split_bar';
  proPct: number;
  conPct: number;
  proLabel: string;
  conLabel: string;
}

export interface CortexTimelineViz {
  kind: 'timeline';
  events: Array<{ day: number; label: string; tone?: 'muted' | 'warn' | 'accent' }>;
  totalDays: number;
}

export type CortexSignalViz = CortexPanelistMixViz | CortexSplitBarViz | CortexTimelineViz;

export interface CortexSignalCard {
  id: string;
  title: string;
  body: string;
  viz: CortexSignalViz;
}

export interface CortexQuoteCard {
  text: string;
  cite: string;
}

export interface CortexClusterBar {
  label: string;
  pct: number;
}

export interface CortexSilverCandidate {
  id: string;
  name: string;
  initials: string;
  tagline: string;
  whyThen: string;
  whyNow: string;
  matchPct: number;
}

export type CortexAnalysisTab = 'diagnosis' | 'reengage';

export interface CortexAnalysisData {
  title: string;
  role: string;
  takeaway: string;
  signals: CortexSignalCard[];
  quotes: CortexQuoteCard[];
  rejectionClusters: CortexClusterBar[];
  silverMedalists: CortexSilverCandidate[];
  activeTab?: CortexAnalysisTab;
}

export interface CortexInsightFixture {
  kind: CortexInsightKind;
  title: string;
  elapsedLabel: string;
  steps: CortexTrailStep[];
  stats: CortexStatCard[];
  messages: CortexInsightMessage[];
  /** Present on flows that render a visual analysis artifact (split pattern). */
  analysis?: CortexAnalysisData;
}

export const CORTEX_INSIGHT_ARTIFACT_ID = 'cortex-insight';
export const CORTEX_ANALYSIS_ARTIFACT_ID = 'cortex-analysis';

/** Per-step reveal delay in ms (stays within 300–500ms). */
export const CORTEX_TRAIL_STAGGER_MS: number[] = [360, 440, 380, 420, 360, 480, 340, 420, 380];

/** Pause between each Cortex chat message landing. */
export const CORTEX_MESSAGE_GAP_MS = 1000;

export const CORTEX_INSIGHTS: Record<CortexInsightKind, CortexInsightFixture> = {
  why_losing: {
    kind: 'why_losing',
    title: 'Close-rate analysis · Staff PM, Platform',
    elapsedLabel: '4.2s',
    steps: [
      {
        num: '01',
        body: 'Query received · scope: close-rate failure analysis · role: staff_pm_platform',
      },
      {
        num: '02',
        body: 'Pulling pipeline history · 28 candidates · 9 reached final round · 0 closed',
      },
      {
        num: '03',
        body: 'Loading interview transcripts · 34 interviews · 142 min audio · 217 evidence nodes',
      },
      {
        num: '04',
        body: 'Analyzing debrief artifacts · 11 group debriefs · extracting drop-off reasons',
      },
      {
        num: '05',
        body: 'Clustering rejection reasons · k-means on candidate exit notes · 3 dominant clusters',
      },
      {
        num: '06',
        body: 'Cross-referencing signals · intake scope vs. interview emphasis vs. Staff PM JD',
      },
      {
        num: '07',
        body: 'Detected pattern: loop drift · panel probed IC execution; role is multi-team leverage',
      },
      {
        num: '08',
        body: 'Running silver-medalist match · 142 past interviews indexed · 3 strong staff-level fits',
      },
      {
        num: '09',
        body: 'Generating analysis artifact · (a) diagnosis tab · (b) re-engage tab',
      },
    ],
    stats: [
      {
        title: 'Cortex memory',
        rows: [
          { label: 'Interviews indexed', value: '142' },
          { label: 'Roles closed', value: '11' },
          { label: 'Silver medalists', value: '38' },
          { label: 'Evidence nodes', value: '2,417' },
        ],
      },
      {
        title: 'Rejection reason clusters',
        rows: [
          { label: 'Scope mismatch', value: '42%' },
          { label: 'Slow follow-through', value: '33%' },
          { label: 'Comp gap', value: '18%' },
          { label: 'Fit / other', value: '7%' },
        ],
      },
    ],
    messages: [],
    analysis: {
      title: 'Close-rate analysis · Staff PM, Platform',
      role: 'Staff PM, Platform',
      takeaway:
        "Not a candidate-quality problem. It's a loop-calibration problem compounded by slow follow-through. Fix the panel briefing with explicit leverage and scope probes, and tighten the post-onsite window to 48 hours.",
      signals: [
        {
          id: 'loop-drift',
          title: 'Loop drift',
          body: "You hired for 'Staff PM, Platform,' but 3 of 4 panelists probed IC execution — shipping velocity, bug triage, metric attribution. The role is about multi-team leverage. Candidates walked away saying it felt like a Senior IC role, not Staff.",
          viz: {
            kind: 'panelist_mix',
            executionLabel: 'Execution probe',
            strategyLabel: 'Leverage / scope probe',
            panelists: [
              { label: 'P1 · Eng lead', probe: 'execution' },
              { label: 'P2 · Platform PM', probe: 'strategy' },
              { label: 'P3 · Design', probe: 'execution' },
              { label: 'P4 · Eng manager', probe: 'execution' },
            ],
          },
        },
        {
          id: 'leadership-contradiction',
          title: 'Leadership contradiction',
          body: 'Across 3 finalists, panels split 50/50 on leadership evidence — same shape every time. Your scorecard has no explicit leadership probe, so interviewers are inventing signals from thin data.',
          viz: {
            kind: 'split_bar',
            proPct: 50,
            conPct: 50,
            proLabel: 'Strong leader signal',
            conLabel: 'Weak / no signal',
          },
        },
        {
          id: 'silver-urgency',
          title: 'Silver-medalist urgency',
          body: '4 of 9 finalists went to competing offers because the second touch came 8+ days after the onsite. Warm candidates went cold.',
          viz: {
            kind: 'timeline',
            totalDays: 10,
            events: [
              { day: 0, label: 'Onsite', tone: 'accent' },
              { day: 6, label: 'Competing offer accepted', tone: 'warn' },
              { day: 8, label: 'Our second touch', tone: 'muted' },
            ],
          },
        },
      ],
      quotes: [
        {
          text: 'The scope in the interviews felt like a Senior IC role, not Staff.',
          cite: 'exit note · Dario O. · panel 3 · week 2',
        },
        {
          text: "I couldn't tell what platform surface I'd actually own in year one.",
          cite: 'exit note · finalist #2 · prior search · Feb',
        },
      ],
      rejectionClusters: [
        { label: 'Scope mismatch', pct: 42 },
        { label: 'Slow follow-through', pct: 33 },
        { label: 'Comp gap', pct: 18 },
        { label: 'Fit / other', pct: 7 },
      ],
      silverMedalists: [
        {
          id: 'jordan-maris',
          name: 'Jordan Maris',
          initials: 'JM',
          tagline: 'Staff PM, Developer Platform · interviewed Feb · 4.1 scorecard',
          whyThen: 'Passed for "role scope mismatch" — not candidate quality.',
          whyNow:
            'Since then, led a cross-team SDK unification at Sentry spanning three squads. Direct match for the platform surface in this JD.',
          matchPct: 91,
        },
        {
          id: 'lena-varga',
          name: 'Lena Varga',
          initials: 'LV',
          tagline: 'Senior PM, Platform · interviewed Q4 · 3.9 scorecard',
          whyThen: 'Declined because "too early for Staff level" at that time.',
          whyNow:
            'Has since led a 4-team platform migration at Vercel — exactly the multi-team leverage story the Staff PM, Platform role needs.',
          matchPct: 88,
        },
        {
          id: 'tomas-palomar',
          name: 'Tomas Palomar',
          initials: 'TP',
          tagline: 'Platform PM · silver medalist last cycle · 4.0 scorecard',
          whyThen: 'Silver medalist — role was backfilled internally.',
          whyNow:
            'Told us in debrief "I want to operate at staff scope." Never re-engaged after rejection. Warm intro still open.',
          matchPct: 86,
        },
      ],
      activeTab: 'diagnosis',
    },
  },
  best_candidate: {
    kind: 'best_candidate',
    title: 'Best-candidate analysis',
    elapsedLabel: '2.8s',
    steps: [
      { num: '01', body: 'Query received · ranking candidates for role fit' },
      { num: '02', body: 'Loading active pipeline · 12 candidates · 4 in final round' },
      {
        num: '03',
        body: 'Indexing evidence per candidate · 28 interview transcripts · 41 scorecard entries',
      },
      {
        num: '04',
        body: 'Weighting by scorecard coverage × interviewer calibration × recency',
      },
      { num: '05', body: 'Debiasing for anchoring (Mark T. spoke first in 6 of 8 debriefs)' },
      { num: '06', body: 'Producing ranked slate with evidence citations' },
    ],
    stats: [
      {
        title: 'Cortex ranking',
        rows: [
          { label: 'Candidates analyzed', value: '12' },
          { label: 'Evidence nodes', value: '217' },
          { label: 'Anchoring risk', value: 'Medium' },
          { label: 'Evidence density', value: '87%' },
        ],
      },
    ],
    messages: [
      {
        who: 'openrecruiting cortex · ranked slate',
        blocks: [
          {
            kind: 'paragraph',
            text: 'Ranking all 12 active candidates by evidence, not opinion volume:',
          },
          {
            kind: 'bullets',
            items: [
              '**#1 · Amara Valeri** — two shipped platform redesigns end-to-end · strongest execution signal · 92 match.',
              '**#2 · Dario Okonkwo** — deeper strategic framing but 2 prior launches slipped by 6+ weeks · execution risk · 88 match.',
              '**#3 · Nia Pettersen** — no direct platform reps · stretch hire on that dimension · 85 match.',
            ],
          },
          {
            kind: 'paragraph',
            text: '**My read:** Amara is the execution bet. If the role were more 0-to-1 strategy, Dario pulls ahead. If you want a longer tail, I can surface the next 5 by asking.',
          },
        ],
      },
    ],
  },
  silver_medalists: {
    kind: 'silver_medalists',
    title: 'Silver-medalist surfacing',
    elapsedLabel: '1.9s',
    steps: [
      { num: '01', body: 'Query received · silver-medalist re-engagement' },
      {
        num: '02',
        body: 'Scanning all past interviews · 142 candidates · 38 classified as silver',
      },
      { num: '03', body: 'Filtering by role-fit vector vs. current open roles' },
      { num: '04', body: 'Ranking by recency × scorecard × "why passed" evidence' },
      { num: '05', body: 'Producing top-3 list with re-engagement rationale' },
    ],
    stats: [
      {
        title: 'Silver-medalist pool',
        rows: [
          { label: 'Total indexed', value: '38' },
          { label: 'Strong role-fit', value: '11' },
          { label: 'Warm (< 6 mo)', value: '17' },
          { label: 'Top-3 surfaced', value: '3' },
        ],
      },
    ],
    messages: [
      {
        who: 'openrecruiting cortex · silver medalists',
        blocks: [
          {
            kind: 'paragraph',
            text: 'Three past finalists worth a fresh look, ranked by role-fit on your current open slate:',
          },
          {
            kind: 'bullets',
            items: [
              '**Jordan Maris** — Staff PM, Developer Platform · Feb · 4.1 scorecard · Sentry SDK unification.',
              '**Lena Varga** — declined Q4, "too early for Staff." Now two years deeper at Vercel.',
              '**Tomas Palomar** — Platform PM silver medalist · self-identifies as staff-scope operator.',
            ],
          },
          {
            kind: 'paragraph',
            text: 'Want me to draft warm re-engagement notes, each anchored in the specific interview moment that earned them this callback?',
          },
        ],
      },
    ],
  },
};

export function detectCortexInsightIntent(input: string): CortexInsightKind | null {
  const n = input.trim().toLowerCase();
  if (!n) return null;
  if (
    n.includes("can't hire") ||
    n.includes('cant hire') ||
    n.includes('not able to hire') ||
    n.includes('not able to close') ||
    n.includes('not closing') ||
    n.includes("aren't we closing") ||
    n.includes("aren't we able to close") ||
    n.includes('arent we able to close') ||
    n.includes('why cant we close') ||
    n.includes("why can't we close") ||
    n.includes('why are we losing') ||
    n.includes('losing candidates') ||
    n.includes('losing in the final') ||
    n.includes('keep losing') ||
    n.includes('close candidates') ||
    n.includes('close rate') ||
    n.includes('close-rate')
  ) {
    return 'why_losing';
  }
  if (
    n.includes('best candidate') ||
    n.includes('who should we hire') ||
    n.includes('which candidate') ||
    n.includes('top candidate') ||
    n.includes('best fit for the role')
  ) {
    return 'best_candidate';
  }
  if (
    n.includes('silver medalist') ||
    n.includes('silver-medalist') ||
    n.includes('re-engage') ||
    n.includes('re engage') ||
    n.includes('past candidates') ||
    n.includes('past interview')
  ) {
    return 'silver_medalists';
  }
  return null;
}
