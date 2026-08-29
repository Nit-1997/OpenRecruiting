export type DebriefVerdict = 'strong_hire' | 'hire' | 'mixed' | 'no_hire';

export type DebriefVote = 'strong_yes' | 'yes' | 'maybe' | 'no' | 'strong_no';

export type DebriefThemeTone = 'pos' | 'neg' | 'neu';

export interface DebriefPanelVote {
  panelist: string;
  panelist_role: string;
  vote: DebriefVote;
  rationale?: string;
}

export interface DebriefCandidateSnapshot {
  candidate_id: string;
  name: string;
  initials: string;
  color: string;
  rank: number;
  verdict: DebriefVerdict;
  headline: string;
  aggregate_score: number;
  score_scale: number;
  rounds_completed: number;
  rounds_total: number;
  top_strengths: string[];
  top_concerns: string[];
  recommendation: string;
  panel_votes: DebriefPanelVote[];
  // Addendum §5: zero scorable cells → render "insufficient"/"—" not the 0.0
  // aggregate. Optional + backward-compatible (absent/false on normal candidates).
  aggregate_insufficient?: boolean;
}

export interface DebriefTheme {
  label: string;
  tone: DebriefThemeTone;
  weight: number; // 0..1
  evidence_count: number;
}

export interface DebriefDecisionRow {
  dimension: string;
  scores: Record<string, number>; // candidate_id → 1..4
  winner_ids: string[];
  note: string;
}

export interface DebriefSourceStats {
  scorecards: number;
  transcripts: number;
}

export interface DebriefPacket {
  id: string;
  requisition_id: string;
  role_title: string;
  title: string;
  subtitle: string;
  generated_at: string;
  generated_by: string;
  // 'draft' is the generate->preview state (the FE previews a draft before
  // committing it via Save); 'superseded' fires the badge, 'draft'/'fresh' don't.
  status: 'fresh' | 'superseded' | 'draft';
  panel_members: Array<{ name: string; role: string; initials: string; color: string }>;
  candidates: DebriefCandidateSnapshot[];
  headline_recommendation: string;
  verdict: DebriefVerdict;
  confidence: 'low' | 'medium' | 'high';
  source_stats: DebriefSourceStats;
  themes: DebriefTheme[];
  decision_matrix: DebriefDecisionRow[];
  risks: string[];
  next_steps: Array<{ label: string; owner?: string; due?: string }>;
}

const PANELISTS_PM = [
  { name: 'Jess Lin', role: 'Recruiter', initials: 'JL', color: '#EADFD4' },
  { name: 'David Woo', role: 'Hiring manager', initials: 'DW', color: '#D8EFE3' },
  { name: 'Sana Reyes', role: 'Principal PM', initials: 'SR', color: '#E9DFF5' },
  { name: 'Anand Patel', role: 'Tech lead', initials: 'AP', color: '#DDE8F6' },
  { name: 'Marcus Chen', role: 'Values', initials: 'MC', color: '#F6E4DA' },
];

const PANELISTS_IOS = [
  { name: 'Jess Lin', role: 'Recruiter', initials: 'JL', color: '#EADFD4' },
  { name: 'Mina Park', role: 'Hiring manager', initials: 'MP', color: '#D8EFE3' },
  { name: 'Ravi Desai', role: 'Tech deep-dive', initials: 'RD', color: '#DDE8F6' },
  { name: 'Elena Vargas', role: 'Values', initials: 'EV', color: '#F6E4DA' },
];

const PANELISTS_DES = [
  { name: 'Sloane Aggarwal', role: 'Recruiter', initials: 'SA', color: '#EADFD4' },
  { name: 'Joon Lee', role: 'Hiring manager', initials: 'JL', color: '#D8EFE3' },
  { name: 'Ilya Volkov', role: 'Craft', initials: 'IV', color: '#E9DFF5' },
  { name: 'Sam Bennett', role: 'Values', initials: 'SB', color: '#F6E4DA' },
];

export const DEBRIEF_PACKETS: Record<string, DebriefPacket[]> = {
  'pm-sfo': [
    {
      id: 'pm-sfo_debrief_2026_04_16',
      requisition_id: 'pm-sfo',
      role_title: 'Staff PM · Sunnyvale',
      title: 'Staff PM final panel debrief',
      subtitle:
        'Synthesis across 5-round loops for 4 candidates — read this before the hiring committee.',
      generated_at: '2026-04-16T18:45:00Z',
      generated_by: 'OpenRecruiting debrief agent',
      status: 'fresh',
      panel_members: PANELISTS_PM,
      verdict: 'strong_hire',
      confidence: 'high',
      source_stats: { scorecards: 17, transcripts: 4 },
      headline_recommendation:
        'Advance Sloane Natarajan to offer; run a parallel track to offer Marcus Chen for the platform bet. Pass on Rivka (keep warm at Senior). Complete David Kim’s final loop before deciding.',
      candidates: [
        {
          candidate_id: 'c1',
          name: 'Sloane Natarajan',
          initials: 'SN',
          color: '#EADFD4',
          rank: 1,
          verdict: 'strong_hire',
          headline:
            'Sharpest product mind on the slate — the only candidate who reframed the prompt unprompted in the panel round.',
          aggregate_score: 3.6,
          score_scale: 4,
          rounds_completed: 5,
          rounds_total: 5,
          top_strengths: [
            'Reframes ambiguous problems in 90 seconds',
            'Direct communicator — pushes back without heat',
            'Values match: specific on repair after conflict',
          ],
          top_concerns: [
            'Infra depth is adequate, not a strength',
            'Comp exceeds band by ~$20k total',
          ],
          recommendation: 'Advance to offer · VP Product loop as closer',
          panel_votes: [
            { panelist: 'Jess Lin', panelist_role: 'Recruiter', vote: 'strong_yes' },
            { panelist: 'David Woo', panelist_role: 'Hiring manager', vote: 'yes' },
            { panelist: 'Sana Reyes', panelist_role: 'Principal PM', vote: 'strong_yes' },
            { panelist: 'Anand Patel', panelist_role: 'Tech lead', vote: 'yes' },
            { panelist: 'Marcus Chen', panelist_role: 'Values', vote: 'strong_yes' },
          ],
        },
        {
          candidate_id: 'c2',
          name: 'Marcus Chen',
          initials: 'MC',
          color: '#D8EFE3',
          rank: 2,
          verdict: 'hire',
          headline:
            'Execution-first platform PM — predictable shipper with the strongest tech fluency we have seen in a year.',
          aggregate_score: 3.4,
          score_scale: 4,
          rounds_completed: 5,
          rounds_total: 5,
          top_strengths: [
            'Whiteboarded a migration plan unprompted',
            'Strongest "mine to fix" ownership signal of the half',
            'Fluent in SQL + reads dashboards independently',
          ],
          top_concerns: [
            'Vision and storytelling are lighter than Sloane',
            'Values round flagged bluntness — worth calibration',
          ],
          recommendation: 'Parallel offer for platform track',
          panel_votes: [
            { panelist: 'Jess Lin', panelist_role: 'Recruiter', vote: 'yes' },
            { panelist: 'David Woo', panelist_role: 'Hiring manager', vote: 'strong_yes' },
            { panelist: 'Sana Reyes', panelist_role: 'Principal PM', vote: 'yes' },
            { panelist: 'Anand Patel', panelist_role: 'Tech lead', vote: 'strong_yes' },
            { panelist: 'Marcus Chen', panelist_role: 'Values', vote: 'maybe' },
          ],
        },
        {
          candidate_id: 'c3',
          name: 'Rivka Sandoval',
          initials: 'RS',
          color: '#E9DFF5',
          rank: 3,
          verdict: 'mixed',
          headline:
            'Magnetic and warm — panel split cleanly on readiness for Staff. Judgement on tradeoffs is the gap.',
          aggregate_score: 2.9,
          score_scale: 4,
          rounds_completed: 4,
          rounds_total: 5,
          top_strengths: [
            'Generates more framing options than anyone this year',
            'Self-aware; named her own gaps unprompted',
            'Strong referrer source — white-glove the pass',
          ],
          top_concerns: [
            'Could not commit to a call when David Woo pressed',
            'Narrates rather than decides',
            'Jess (4) and David (2) are emphatic in opposite directions',
          ],
          recommendation: 'Pass on Staff · keep warm for Senior PM openings',
          panel_votes: [
            { panelist: 'Jess Lin', panelist_role: 'Recruiter', vote: 'strong_yes' },
            { panelist: 'David Woo', panelist_role: 'Hiring manager', vote: 'no' },
            { panelist: 'Sana Reyes', panelist_role: 'Principal PM', vote: 'maybe' },
            { panelist: 'Marcus Chen', panelist_role: 'Values', vote: 'yes' },
          ],
        },
        {
          candidate_id: 'c4',
          name: 'David Kim',
          initials: 'DK',
          color: '#F6E4DA',
          rank: 4,
          verdict: 'mixed',
          headline:
            'Quiet-confident and steady — only 3 of 4 rounds scored, cannot decide until the loop closes.',
          aggregate_score: 3.0,
          score_scale: 4,
          rounds_completed: 3,
          rounds_total: 4,
          top_strengths: [
            'Clean mental model of PM value on a platform bet',
            'Domain familiarity from earlier Lyft tour',
          ],
          top_concerns: ['Technical depth not yet probed', 'Values round outstanding'],
          recommendation: 'Hold — complete the loop this week before deciding',
          panel_votes: [
            { panelist: 'Jess Lin', panelist_role: 'Recruiter', vote: 'yes' },
            { panelist: 'David Woo', panelist_role: 'Hiring manager', vote: 'yes' },
            { panelist: 'Sana Reyes', panelist_role: 'Principal PM', vote: 'maybe' },
          ],
        },
      ],
      themes: [
        { label: 'Reframing in ambiguity', tone: 'pos', weight: 0.9, evidence_count: 4 },
        { label: 'Execution predictability', tone: 'pos', weight: 0.8, evidence_count: 3 },
        { label: 'Tech fluency beyond rubric', tone: 'pos', weight: 0.7, evidence_count: 3 },
        { label: 'Decisiveness under pressure', tone: 'neg', weight: 0.6, evidence_count: 3 },
        { label: 'Panel disagreement on Staff bar', tone: 'neu', weight: 0.55, evidence_count: 2 },
        { label: 'Comp band pressure', tone: 'neg', weight: 0.4, evidence_count: 2 },
      ],
      decision_matrix: [
        {
          dimension: 'Product sense',
          scores: { c1: 4, c2: 3, c3: 3, c4: 3 },
          winner_ids: ['c1'],
          note: 'Sloane reframed the prompt in 90s — rare Staff signal.',
        },
        {
          dimension: 'Strategy & vision',
          scores: { c1: 4, c2: 3, c3: 3, c4: 3 },
          winner_ids: ['c1'],
          note: 'Sloane connected the bet to a 3-year narrative; Marcus kept it to next quarter.',
        },
        {
          dimension: 'Execution & scoping',
          scores: { c1: 3, c2: 4, c3: 2, c4: 3 },
          winner_ids: ['c2'],
          note: 'Marcus broke ambiguity into three workstreams with acceptance criteria.',
        },
        {
          dimension: 'Technical depth',
          scores: { c1: 3, c2: 4, c3: 2, c4: 2 },
          winner_ids: ['c2'],
          note: 'Marcus whiteboarded a migration plan unprompted — Sloane and Rivka reached for PM frames.',
        },
        {
          dimension: 'Communication',
          scores: { c1: 4, c2: 3, c3: 4, c4: 3 },
          winner_ids: ['c1', 'c3'],
          note: 'Rivka is magnetic; Sloane is direct and specific. Marcus is clipped.',
        },
        {
          dimension: 'Culture & values',
          scores: { c1: 4, c2: 3, c3: 3, c4: 2 },
          winner_ids: ['c1'],
          note: 'Sloane named a specific repair story; David Kim has not been probed.',
        },
      ],
      risks: [
        'Sloane’s total comp target is ~$380k; band tops at $360k — finance review needed before verbal.',
        'Marcus read "blunt" in values; add a pre-offer calibration chat with David.',
        'Rivka is a repeat referrer source — pass must be white-glove or we lose the pipeline.',
        'David Kim still has one round outstanding — do not force a decision this week.',
      ],
      next_steps: [
        {
          label: 'Finance review on Sloane’s comp band',
          owner: 'David Woo',
          due: '2026-04-18',
        },
        {
          label: 'Loop Sloane with Rhea (VP Product) for 30-min alignment',
          owner: 'Jess Lin',
          due: '2026-04-17',
        },
        {
          label: 'Schedule David Kim’s culture round',
          owner: 'Jess Lin',
          due: '2026-04-18',
        },
        {
          label: 'White-glove pass call with Rivka + referral thank-you',
          owner: 'Jess Lin',
          due: '2026-04-19',
        },
        {
          label: 'Pre-offer calibration chat with Marcus',
          owner: 'David Woo',
          due: '2026-04-18',
        },
      ],
    },
    {
      id: 'pm-sfo_debrief_2026_04_11',
      requisition_id: 'pm-sfo',
      role_title: 'Staff PM · Sunnyvale',
      title: 'Mid-loop debrief — panel snapshot',
      subtitle: 'Earlier snapshot after panel round, before culture and values interviews closed.',
      generated_at: '2026-04-11T21:10:00Z',
      generated_by: 'OpenRecruiting debrief agent',
      status: 'superseded',
      panel_members: PANELISTS_PM,
      verdict: 'hire',
      confidence: 'medium',
      source_stats: { scorecards: 9, transcripts: 3 },
      headline_recommendation:
        'Sloane and Marcus are both panel-bar; wait on culture + values before a final call. Rivka is trending toward a pass.',
      candidates: [
        {
          candidate_id: 'c1',
          name: 'Sloane Natarajan',
          initials: 'SN',
          color: '#EADFD4',
          rank: 1,
          verdict: 'hire',
          headline: 'Panel round was the best Sana has seen this half. Values still outstanding.',
          aggregate_score: 3.5,
          score_scale: 4,
          rounds_completed: 3,
          rounds_total: 5,
          top_strengths: ['Reframing', 'Prioritization tradeoffs'],
          top_concerns: ['Infra depth'],
          recommendation: 'Continue loop — strong trend.',
          panel_votes: [
            { panelist: 'Jess Lin', panelist_role: 'Recruiter', vote: 'strong_yes' },
            { panelist: 'David Woo', panelist_role: 'Hiring manager', vote: 'yes' },
            { panelist: 'Sana Reyes', panelist_role: 'Principal PM', vote: 'strong_yes' },
          ],
        },
        {
          candidate_id: 'c2',
          name: 'Marcus Chen',
          initials: 'MC',
          color: '#D8EFE3',
          rank: 2,
          verdict: 'hire',
          headline: 'Best execution signal of the half. Iteration over generation.',
          aggregate_score: 3.3,
          score_scale: 4,
          rounds_completed: 3,
          rounds_total: 5,
          top_strengths: ['Execution', 'Tech fluency'],
          top_concerns: ['Vision'],
          recommendation: 'Continue loop — parallel track possible.',
          panel_votes: [
            { panelist: 'Jess Lin', panelist_role: 'Recruiter', vote: 'yes' },
            { panelist: 'David Woo', panelist_role: 'Hiring manager', vote: 'strong_yes' },
            { panelist: 'Sana Reyes', panelist_role: 'Principal PM', vote: 'yes' },
          ],
        },
        {
          candidate_id: 'c3',
          name: 'Rivka Sandoval',
          initials: 'RS',
          color: '#E9DFF5',
          rank: 3,
          verdict: 'mixed',
          headline: 'Split panel. Jess loves her; David lost her on prioritization.',
          aggregate_score: 2.8,
          score_scale: 4,
          rounds_completed: 3,
          rounds_total: 5,
          top_strengths: ['Ideation', 'Likability'],
          top_concerns: ['Judgement on tradeoffs'],
          recommendation: 'Trending toward pass — values round may reset.',
          panel_votes: [
            { panelist: 'Jess Lin', panelist_role: 'Recruiter', vote: 'strong_yes' },
            { panelist: 'David Woo', panelist_role: 'Hiring manager', vote: 'no' },
            { panelist: 'Sana Reyes', panelist_role: 'Principal PM', vote: 'maybe' },
          ],
        },
      ],
      themes: [
        { label: 'Reframing', tone: 'pos', weight: 0.8, evidence_count: 2 },
        { label: 'Execution strength', tone: 'pos', weight: 0.7, evidence_count: 2 },
        { label: 'Panel disagreement', tone: 'neu', weight: 0.6, evidence_count: 1 },
      ],
      decision_matrix: [
        {
          dimension: 'Product sense',
          scores: { c1: 4, c2: 3, c3: 3 },
          winner_ids: ['c1'],
          note: 'Sloane is consistently ahead on reframing.',
        },
        {
          dimension: 'Execution',
          scores: { c1: 3, c2: 4, c3: 2 },
          winner_ids: ['c2'],
          note: 'Marcus is the cleanest shipper on the slate.',
        },
        {
          dimension: 'Communication',
          scores: { c1: 4, c2: 3, c3: 4 },
          winner_ids: ['c1', 'c3'],
          note: 'Rivka matches Sloane on charisma; Sloane wins on clarity.',
        },
      ],
      risks: [
        'Panel disagreement on Rivka is widening by round — don’t force a decision yet.',
        'Compensation not yet surfaced with Sloane.',
      ],
      next_steps: [
        { label: 'Send values round prompts to panel', owner: 'Jess Lin', due: '2026-04-12' },
        { label: 'Ask recruiter to probe Sloane on comp', owner: 'Jess Lin', due: '2026-04-13' },
      ],
    },
  ],
  'ios-sea': [
    {
      id: 'ios-sea_debrief_2026_04_13',
      requisition_id: 'ios-sea',
      role_title: 'Senior iOS Eng',
      title: 'Senior iOS panel debrief',
      subtitle: 'Comparing Noor and Jamie after deep-dive + values rounds.',
      generated_at: '2026-04-13T15:00:00Z',
      generated_by: 'OpenRecruiting debrief agent',
      status: 'fresh',
      panel_members: PANELISTS_IOS,
      verdict: 'strong_hire',
      confidence: 'high',
      source_stats: { scorecards: 7, transcripts: 2 },
      headline_recommendation:
        'Advance Noor Haidari to offer. Hold Jamie Wu for a product deep-dive — strong craft, missing one probe.',
      candidates: [
        {
          candidate_id: 'd1',
          name: 'Noor Haidari',
          initials: 'NH',
          color: '#E9DFF5',
          rank: 1,
          verdict: 'strong_hire',
          headline:
            'Systems-minded iOS eng with the cleanest concurrency walkthrough Mina has seen in a year.',
          aggregate_score: 3.5,
          score_scale: 4,
          rounds_completed: 4,
          rounds_total: 4,
          top_strengths: [
            'Swift concurrency — real-world examples, not textbook',
            'Testing discipline (snapshot + integration, flake rate-aware)',
            'Wrote real tests in real code — not pseudocode',
          ],
          top_concerns: [
            'Metal/GPU work thinner than the nice-to-have implies',
            'Targeting top of band on comp',
          ],
          recommendation: 'Advance to offer after reference + comp review.',
          panel_votes: [
            { panelist: 'Jess Lin', panelist_role: 'Recruiter', vote: 'strong_yes' },
            { panelist: 'Mina Park', panelist_role: 'Hiring manager', vote: 'yes' },
            { panelist: 'Ravi Desai', panelist_role: 'Tech deep-dive', vote: 'strong_yes' },
            { panelist: 'Elena Vargas', panelist_role: 'Values', vote: 'yes' },
          ],
        },
        {
          candidate_id: 'd2',
          name: 'Jamie Wu',
          initials: 'JW',
          color: '#D8EFE3',
          rank: 2,
          verdict: 'mixed',
          headline:
            'Craft-first engineer with exceptional UIKit fundamentals — greenfield experience is thinner.',
          aggregate_score: 3.2,
          score_scale: 4,
          rounds_completed: 3,
          rounds_total: 4,
          top_strengths: [
            'UIKit + animation fidelity',
            'Catches UX bugs during implementation',
            'Live code on perf walkthrough',
          ],
          top_concerns: [
            'Greenfield / 0-to-1 is lighter than the role shape',
            'Product instincts were asserted but not probed',
          ],
          recommendation: 'Hold for product deep-dive with PM lead.',
          panel_votes: [
            { panelist: 'Jess Lin', panelist_role: 'Recruiter', vote: 'yes' },
            { panelist: 'Mina Park', panelist_role: 'Hiring manager', vote: 'yes' },
            { panelist: 'Ravi Desai', panelist_role: 'Tech deep-dive', vote: 'strong_yes' },
          ],
        },
      ],
      themes: [
        { label: 'Real code, not slides', tone: 'pos', weight: 0.9, evidence_count: 3 },
        { label: 'Testing discipline', tone: 'pos', weight: 0.7, evidence_count: 2 },
        { label: 'Greenfield exposure gap', tone: 'neg', weight: 0.5, evidence_count: 2 },
      ],
      decision_matrix: [
        {
          dimension: 'Systems thinking',
          scores: { d1: 4, d2: 3 },
          winner_ids: ['d1'],
          note: 'Noor walked a full migration; Jamie scoped narrower.',
        },
        {
          dimension: 'Craft & polish',
          scores: { d1: 3, d2: 4 },
          winner_ids: ['d2'],
          note: 'Jamie’s UIKit/animation work is the strongest on the slate.',
        },
        {
          dimension: 'Testing discipline',
          scores: { d1: 4, d2: 3 },
          winner_ids: ['d1'],
          note: 'Noor is flake-rate aware; rare signal for mobile.',
        },
        {
          dimension: 'Greenfield comfort',
          scores: { d1: 3, d2: 2 },
          winner_ids: ['d1'],
          note: 'Neither candidate stretches here; Noor is closer.',
        },
      ],
      risks: [
        'Noor’s comp expectations top-of-band — get finance aligned before we extend.',
        'Jamie’s product instincts unproven; skipping the deep-dive risks a regret-hire.',
      ],
      next_steps: [
        {
          label: 'Reference call with Noor’s previous tech lead',
          owner: 'Jess Lin',
          due: '2026-04-14',
        },
        {
          label: 'Schedule Jamie’s product deep-dive with PM lead',
          owner: 'Mina Park',
          due: '2026-04-15',
        },
        { label: 'Finance review on Noor comp', owner: 'Mina Park', due: '2026-04-14' },
      ],
    },
  ],
  'des-ldn': [
    {
      id: 'des-ldn_debrief_2026_04_12',
      requisition_id: 'des-ldn',
      role_title: 'Product Designer · London',
      title: 'Product designer panel debrief',
      subtitle:
        'Single-candidate synthesis for Noor Haidari — time-zone call needed before extending.',
      generated_at: '2026-04-12T10:30:00Z',
      generated_by: 'OpenRecruiting debrief agent',
      status: 'fresh',
      panel_members: PANELISTS_DES,
      verdict: 'hire',
      confidence: 'medium',
      source_stats: { scorecards: 4, transcripts: 1 },
      headline_recommendation:
        'Advance Noor with a pre-offer conversation on time-zone and product-tradeoff expectations.',
      candidates: [
        {
          candidate_id: 'd1',
          name: 'Noor Haidari',
          initials: 'NH',
          color: '#E9DFF5',
          rank: 1,
          verdict: 'hire',
          headline:
            'Crisp systems thinking + motion craft beyond the usual Lottie-polish. Product judgement is the watch-item.',
          aggregate_score: 3.4,
          score_scale: 4,
          rounds_completed: 4,
          rounds_total: 4,
          top_strengths: [
            'Token library at scale',
            'Genuine motion depth — not surface polish',
            'Low ego, high curiosity',
          ],
          top_concerns: [
            'Product judgement untested at Staff context',
            'London ↔ SF overlap is workable, not ideal',
          ],
          recommendation: 'Advance — align on timezone + product tradeoffs first.',
          panel_votes: [
            { panelist: 'Sloane Aggarwal', panelist_role: 'Recruiter', vote: 'strong_yes' },
            { panelist: 'Joon Lee', panelist_role: 'Hiring manager', vote: 'yes' },
            { panelist: 'Ilya Volkov', panelist_role: 'Craft', vote: 'strong_yes' },
            { panelist: 'Sam Bennett', panelist_role: 'Values', vote: 'yes' },
          ],
        },
      ],
      themes: [
        { label: 'Craft beyond polish', tone: 'pos', weight: 0.9, evidence_count: 3 },
        { label: 'Systems + tokens at scale', tone: 'pos', weight: 0.7, evidence_count: 2 },
        { label: 'Time-zone overlap', tone: 'neu', weight: 0.5, evidence_count: 1 },
        { label: 'Staff-level tradeoffs untested', tone: 'neg', weight: 0.45, evidence_count: 1 },
      ],
      decision_matrix: [
        {
          dimension: 'Design systems',
          scores: { d1: 4 },
          winner_ids: ['d1'],
          note: 'Maintained token library at scale — load-bearing signal for this role.',
        },
        {
          dimension: 'Motion craft',
          scores: { d1: 4 },
          winner_ids: ['d1'],
          note: 'Motion reel caused Ilya to re-open the recruiter loop.',
        },
        {
          dimension: 'Product tradeoffs',
          scores: { d1: 3 },
          winner_ids: ['d1'],
          note: 'Adequate, not yet tested in a Staff context.',
        },
        {
          dimension: 'Collaboration',
          scores: { d1: 4 },
          winner_ids: ['d1'],
          note: 'Two interviewers requested her for their team unprompted.',
        },
      ],
      risks: [
        'Product judgement at Staff bar is inferred, not measured — schedule a follow-up with a tradeoff-heavy prompt.',
        'Time-zone overlap with SF core hours is ~3h/day — align with TL before extending.',
      ],
      next_steps: [
        {
          label: 'Reference call with previous design lead',
          owner: 'Sloane Aggarwal',
          due: '2026-04-13',
        },
        {
          label: 'Pre-offer conversation on timezone with TLs',
          owner: 'Joon Lee',
          due: '2026-04-14',
        },
        {
          label: 'Follow-up product tradeoff prompt',
          owner: 'Joon Lee',
          due: '2026-04-14',
        },
      ],
    },
  ],
};

export function getDebriefPackets(roleId: string): DebriefPacket[] {
  return DEBRIEF_PACKETS[roleId] ?? [];
}

export function getDebriefPacket(roleId: string, packetId: string): DebriefPacket | null {
  return DEBRIEF_PACKETS[roleId]?.find((p) => p.id === packetId) ?? null;
}
