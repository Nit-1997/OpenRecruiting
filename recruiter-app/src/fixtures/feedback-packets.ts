export type PacketVerdict = 'strong' | 'mixed' | 'pass';

export type PacketQuoteType = 'strength' | 'concern';

export interface PacketRoundQuote {
  text: string;
  type: PacketQuoteType;
  attribution?: string;
}

export interface PacketRound {
  id: string;
  title: string;
  interviewer: string;
  date: string;
  score: 1 | 2 | 3 | 4;
  notes: string;
  quotes: PacketRoundQuote[];
}

export interface PacketPanelist {
  name: string;
  role: string;
  score: number;
}

export interface PacketOverall {
  summary: string;
  strengths: string[];
  watchouts: string[];
  nextSteps: string[];
  verdict: PacketVerdict;
}

export interface FeedbackPacket {
  candidateId: string;
  candidateName: string;
  candidateAvatar: string;
  candidateColor: string;
  candidateStage: string;
  roleId: string;
  roleTitle: string;
  aggregateScore: number;
  scoreScale: number;
  overall: PacketOverall;
  rounds: PacketRound[];
  panelistsPanel?: PacketPanelist[];
  recommendation?: string;
  read: boolean;
}

// Multi-role × multi-candidate packet library. First key is roleId, second key
// is candidateId. Each packet is fully self-contained so the artifact can render
// without looking anything else up.
export const FEEDBACK_PACKETS: Record<string, Record<string, FeedbackPacket>> = {
  'pm-sfo': {
    c1: {
      candidateId: 'c1',
      candidateName: 'Sloane Natarajan',
      candidateAvatar: 'PN',
      candidateColor: '#EADFD4',
      candidateStage: 'Panel complete',
      roleId: 'pm-sfo',
      roleTitle: 'Staff PM · Sunnyvale',
      aggregateScore: 3.6,
      scoreScale: 4,
      overall: {
        summary:
          'Sloane is a product-led Staff PM with sharp prioritization, a clear framework for vague problems, and a warm but direct communication style. Strongest on strategy, lightest on 0-to-1 infra.',
        strengths: [
          'Product sense — breaks ambiguous problems into first-principles frameworks quickly.',
          'Communication — direct, specific, pushes back on the panel without heat.',
          'Leadership signal — Sana and Marcus both flagged her as someone they would want to be PM-d by.',
        ],
        watchouts: [
          'Infra and technical depth — adequate but not a strength. Pair her with a senior EM.',
          'Comp alignment — current total comp is ~$380k; band tops at $360k.',
          'Start date — 4-week notice means earliest start is May 19.',
        ],
        nextSteps: [
          'Loop Sloane with Rhea (VP Product) for an informal 30-min alignment.',
          'Finance review on comp band before Friday.',
          'Target verbal offer by Friday EOD.',
        ],
        verdict: 'strong',
      },
      rounds: [
        {
          id: 'rs',
          title: 'Recruiter screen',
          interviewer: 'Jess Lin',
          date: '2026-04-03',
          score: 4,
          notes:
            'Clear on motivations, strong narrative on her Sprout Social impact. Asked smart questions about product vision.',
          quotes: [
            {
              text: 'Best screen Jess has run this half — crisp story, no fluff.',
              type: 'strength',
              attribution: 'Jess Lin',
            },
          ],
        },
        {
          id: 'hm',
          title: 'Hiring manager',
          interviewer: 'David Woo',
          date: '2026-04-07',
          score: 3,
          notes:
            'Strong on prioritization trade-offs. Gave a structured answer on the retention question, less opinionated on infra.',
          quotes: [
            {
              text: 'She walked me through three tradeoffs I had not considered on retention.',
              type: 'strength',
              attribution: 'David Woo',
            },
            {
              text: 'Leaned away from infra questions — fine for now, but a watch-item.',
              type: 'concern',
              attribution: 'David Woo',
            },
          ],
        },
        {
          id: 'ps',
          title: 'Product sense & strategy',
          interviewer: 'Sana Reyes',
          date: '2026-04-10',
          score: 4,
          notes:
            'Best product sense interview Sana has seen this half. Reframed the stated question in a way that revealed a cleaner product cut.',
          quotes: [
            {
              text: 'Sloane reframed the prompt in 90 seconds and saved us 40 minutes of bad path.',
              type: 'strength',
              attribution: 'Sana Reyes',
            },
          ],
        },
        {
          id: 'an',
          title: 'Technical / analytics',
          interviewer: 'Anand Patel',
          date: '2026-04-11',
          score: 3,
          notes:
            'Comfortable with metrics, shallow on infra fundamentals. We knew this going in; score matches the rubric.',
          quotes: [
            {
              text: 'Fluent in dashboards, reached for a PM framework when a system frame was needed.',
              type: 'concern',
              attribution: 'Anand Patel',
            },
          ],
        },
        {
          id: 'cv',
          title: 'Culture & values',
          interviewer: 'Marcus Chen',
          date: '2026-04-12',
          score: 4,
          notes: 'Thoughtful on disagreement; named specific examples of repair after conflict.',
          quotes: [
            {
              text: 'One of the best answers I have heard on “tell me about a conflict with an eng lead.”',
              type: 'strength',
              attribution: 'Marcus Chen',
            },
          ],
        },
      ],
      panelistsPanel: [
        { name: 'Jess Lin', role: 'Recruiter', score: 4 },
        { name: 'David Woo', role: 'Hiring manager', score: 3 },
        { name: 'Sana Reyes', role: 'Principal PM', score: 4 },
        { name: 'Anand Patel', role: 'Tech lead', score: 3 },
        { name: 'Marcus Chen', role: 'Values', score: 4 },
      ],
      recommendation: 'Advance to offer',
      read: false,
    },
    c2: {
      candidateId: 'c2',
      candidateName: 'Marcus Chen',
      candidateAvatar: 'MC',
      candidateColor: '#D8EFE3',
      candidateStage: 'Panel complete',
      roleId: 'pm-sfo',
      roleTitle: 'Staff PM · Sunnyvale',
      aggregateScore: 3.4,
      scoreScale: 4,
      overall: {
        summary:
          'Marcus is the execution-first PM on the slate — exceptional ownership, slightly less dimension on vision. Good match for a scoped platform bet where predictability matters more than reframing.',
        strengths: [
          'Execution — ships predictably, sharp on scoping and stage-gating.',
          'Technical fluency — comfortable in code, reads dashboards independently.',
          'Ownership — the strongest “mine to fix” signal on the panel this half.',
        ],
        watchouts: [
          'Vision and storytelling — lighter than Sloane; will need an EM or designer strong on narrative.',
          'External polish — more reps with execs before a big keynote moment.',
        ],
        nextSteps: [
          'David to calibrate with Marcus’s 2 scheduled references.',
          'Share written case study from the take-home with VP Eng.',
          'Tentative offer conversation next Tuesday.',
        ],
        verdict: 'strong',
      },
      rounds: [
        {
          id: 'rs',
          title: 'Recruiter screen',
          interviewer: 'Jess Lin',
          date: '2026-04-02',
          score: 3,
          notes:
            'Strong interest in the infra thesis; asked smart questions about margin structure and team composition.',
          quotes: [
            {
              text: 'Asked the sharpest margin question I have heard from a PM candidate this quarter.',
              type: 'strength',
              attribution: 'Jess Lin',
            },
          ],
        },
        {
          id: 'hm',
          title: 'Hiring manager',
          interviewer: 'David Woo',
          date: '2026-04-06',
          score: 4,
          notes:
            'Best execution signal David has seen this half. Took a messy problem, structured it, and delivered.',
          quotes: [
            {
              text: 'He reframed the delivery problem into three workstreams with acceptance criteria.',
              type: 'strength',
              attribution: 'David Woo',
            },
          ],
        },
        {
          id: 'ps',
          title: 'Product sense & strategy',
          interviewer: 'Sana Reyes',
          date: '2026-04-09',
          score: 3,
          notes:
            'Solid but more iterative than generative. Did not reframe the problem. Would be great behind a reframer.',
          quotes: [
            {
              text: 'Iterative, not generative — solid, not exciting.',
              type: 'concern',
              attribution: 'Sana Reyes',
            },
          ],
        },
        {
          id: 'an',
          title: 'Technical / analytics',
          interviewer: 'Anand Patel',
          date: '2026-04-10',
          score: 4,
          notes:
            'Fluent in SQL, can whiteboard a migration plan. Rare for PM — genuine systems thinker.',
          quotes: [
            {
              text: 'He whiteboarded the migration plan unprompted. That is rare for a PM.',
              type: 'strength',
              attribution: 'Anand Patel',
            },
          ],
        },
        {
          id: 'cv',
          title: 'Culture & values',
          interviewer: 'Marcus Chen',
          date: '2026-04-11',
          score: 3,
          notes: 'Direct, occasionally clipped. Not a blocker but worth a values calibration chat.',
          quotes: [
            {
              text: 'Comes across as blunt — it is honesty, not coldness, but worth surfacing to the team.',
              type: 'concern',
              attribution: 'Marcus Chen',
            },
          ],
        },
      ],
      panelistsPanel: [
        { name: 'Jess Lin', role: 'Recruiter', score: 3 },
        { name: 'David Woo', role: 'Hiring manager', score: 4 },
        { name: 'Sana Reyes', role: 'Principal PM', score: 3 },
        { name: 'Anand Patel', role: 'Tech lead', score: 4 },
        { name: 'Marcus Chen', role: 'Values', score: 3 },
      ],
      recommendation: 'Advance to offer',
      read: false,
    },
    c3: {
      candidateId: 'c3',
      candidateName: 'Rivka Sandoval',
      candidateAvatar: 'RS',
      candidateColor: '#E9DFF5',
      candidateStage: 'Panel complete',
      roleId: 'pm-sfo',
      roleTitle: 'Staff PM · Sunnyvale',
      aggregateScore: 2.9,
      scoreScale: 4,
      overall: {
        summary:
          'Rivka is sharp and likable, but the panel is split on readiness for Staff. Product sense is there; judgement on tradeoffs is not yet.',
        strengths: [
          'Ideation and framing — generates more options than most PMs we have seen this year.',
          'Self-awareness — named her own gaps unprompted.',
          'Candidate experience — would be a strong referrer even as a pass.',
        ],
        watchouts: [
          'Judgement on tradeoffs — critical for Staff level, not yet there.',
          'Structured communication — tends to narrate rather than decide.',
          'Panel disagreement — Jess (4) and David (2.5) are both emphatic. Worth calibration.',
        ],
        nextSteps: [
          'Share pass decision with white-glove note — Jess to deliver.',
          'Flag as “keep warm” for Senior PM openings in next 6 months.',
          'Send a thank-you gift — Rivka is a repeat referrer source.',
        ],
        verdict: 'mixed',
      },
      rounds: [
        {
          id: 'rs',
          title: 'Recruiter screen',
          interviewer: 'Jess Lin',
          date: '2026-04-04',
          score: 4,
          notes: 'Magnetic. Jess flagged as best screen of the quarter.',
          quotes: [
            {
              text: 'Best screen of the quarter. Full stop.',
              type: 'strength',
              attribution: 'Jess Lin',
            },
          ],
        },
        {
          id: 'hm',
          title: 'Hiring manager',
          interviewer: 'David Woo',
          date: '2026-04-08',
          score: 2,
          notes: 'Lost David on prioritization — could not articulate why one bet beat another.',
          quotes: [
            {
              text: 'She gave me three options; she never gave me her call.',
              type: 'concern',
              attribution: 'David Woo',
            },
          ],
        },
        {
          id: 'ps',
          title: 'Product sense & strategy',
          interviewer: 'Sana Reyes',
          date: '2026-04-10',
          score: 3,
          notes: 'Lots of ideas, less judgement. Would be strong at Senior but not Staff.',
          quotes: [
            {
              text: 'Big idea space, thin judgement. Senior fit, not Staff.',
              type: 'concern',
              attribution: 'Sana Reyes',
            },
          ],
        },
        {
          id: 'cv',
          title: 'Culture & values',
          interviewer: 'Marcus Chen',
          date: '2026-04-12',
          score: 3,
          notes: 'Warm, self-aware, owned the gaps David surfaced. No concerns on values.',
          quotes: [
            {
              text: 'She named her own gaps before I could. That is rare.',
              type: 'strength',
              attribution: 'Marcus Chen',
            },
          ],
        },
      ],
      panelistsPanel: [
        { name: 'Jess Lin', role: 'Recruiter', score: 4 },
        { name: 'David Woo', role: 'Hiring manager', score: 2 },
        { name: 'Sana Reyes', role: 'Principal PM', score: 3 },
        { name: 'Marcus Chen', role: 'Values', score: 3 },
      ],
      recommendation: 'Pass — keep warm for Senior',
      read: false,
    },
    c4: {
      candidateId: 'c4',
      candidateName: 'David Kim',
      candidateAvatar: 'DK',
      candidateColor: '#F6E4DA',
      candidateStage: 'HM + panel done',
      roleId: 'pm-sfo',
      roleTitle: 'Staff PM · Sunnyvale',
      aggregateScore: 3.0,
      scoreScale: 4,
      overall: {
        summary:
          'David is early in the loop — strong hiring-manager signal, waiting on the culture round. Steady on scope; the depth question has not been probed yet.',
        strengths: [
          'Scope thinking — clean mental model of where PM value lives in a platform bet.',
          'Stakeholder management — David W. flagged him as one to “watch for skip-level posture.”',
        ],
        watchouts: [
          'Only 3 of 4 rounds scored — panel loop still open.',
          'Depth on technical fundamentals not yet probed.',
        ],
        nextSteps: [
          'Schedule the culture round this week.',
          'Do not move to decision until all 4 scorecards are in.',
        ],
        verdict: 'mixed',
      },
      rounds: [
        {
          id: 'rs',
          title: 'Recruiter screen',
          interviewer: 'Jess Lin',
          date: '2026-04-05',
          score: 3,
          notes: 'Clear, quiet confidence. Knows the domain from a Lyft tour earlier.',
          quotes: [
            {
              text: 'Quiet-confident — the kind we sometimes under-index on early.',
              type: 'strength',
              attribution: 'Jess Lin',
            },
          ],
        },
        {
          id: 'hm',
          title: 'Hiring manager',
          interviewer: 'David Woo',
          date: '2026-04-09',
          score: 3,
          notes: 'Steady, structured. Not exceptional, no red flags.',
          quotes: [
            {
              text: 'Steady. Not exciting, not concerning.',
              type: 'strength',
              attribution: 'David Woo',
            },
          ],
        },
        {
          id: 'ps',
          title: 'Product sense & strategy',
          interviewer: 'Sana Reyes',
          date: '2026-04-11',
          score: 3,
          notes: 'Competent. Would benefit from a deeper probe next round.',
          quotes: [
            {
              text: 'Competent — I want more signal before I commit.',
              type: 'concern',
              attribution: 'Sana Reyes',
            },
          ],
        },
      ],
      panelistsPanel: [
        { name: 'Jess Lin', role: 'Recruiter', score: 3 },
        { name: 'David Woo', role: 'Hiring manager', score: 3 },
        { name: 'Sana Reyes', role: 'Principal PM', score: 3 },
      ],
      recommendation: 'Hold — complete the loop',
      read: false,
    },
  },
  'ios-sea': {
    d1: {
      candidateId: 'd1',
      candidateName: 'Noor Haidari',
      candidateAvatar: 'NH',
      candidateColor: '#E9DFF5',
      candidateStage: 'Panel complete',
      roleId: 'ios-sea',
      roleTitle: 'Senior iOS Eng',
      aggregateScore: 3.5,
      scoreScale: 4,
      overall: {
        summary:
          'Noor is a strong systems-minded iOS engineer. Sharp on Swift concurrency, calm under a whiteboard probe, and unusually clear on testing strategy for a mobile candidate.',
        strengths: [
          'Swift concurrency and structured concurrency — confident, real-world examples.',
          'Testing discipline — advocates snapshot + integration and talks about flake rate.',
          'Cross-team communication — worked tightly with a growth team; speaks PM fluently.',
        ],
        watchouts: [
          'Metal / GPU work is lighter than the “nice to have” implies.',
          'Compensation expectations — targeting top of band.',
        ],
        nextSteps: [
          'Reference call with previous tech lead scheduled for Thursday.',
          'Comp conversation with finance before extending.',
        ],
        verdict: 'strong',
      },
      rounds: [
        {
          id: 'rs',
          title: 'Recruiter screen',
          interviewer: 'Jess Lin',
          date: '2026-04-05',
          score: 4,
          notes: 'Clear on motivations; specifically wants a platform role not a feature-shop.',
          quotes: [
            {
              text: 'She named the exact shape of role we are offering unprompted.',
              type: 'strength',
              attribution: 'Jess Lin',
            },
          ],
        },
        {
          id: 'hm',
          title: 'Hiring manager',
          interviewer: 'Mina Park',
          date: '2026-04-08',
          score: 3,
          notes: 'Strong on systems thinking; walked through a concurrency migration plan cleanly.',
          quotes: [
            {
              text: 'Cleanest concurrency walkthrough I have seen in a year of interviewing.',
              type: 'strength',
              attribution: 'Mina Park',
            },
          ],
        },
        {
          id: 'tech',
          title: 'Technical deep-dive',
          interviewer: 'Ravi Desai',
          date: '2026-04-10',
          score: 4,
          notes: 'Paired on a UIKit-to-SwiftUI migration scenario. Real code, real tradeoffs.',
          quotes: [
            {
              text: 'She wrote real tests in real code — not pseudocode. Rare signal.',
              type: 'strength',
              attribution: 'Ravi Desai',
            },
          ],
        },
        {
          id: 'cv',
          title: 'Culture & values',
          interviewer: 'Elena Vargas',
          date: '2026-04-12',
          score: 3,
          notes: 'Calm, direct, owned a recent failure story convincingly.',
          quotes: [
            {
              text: 'Owned a tough story about a bad migration — did not spin it.',
              type: 'strength',
              attribution: 'Elena Vargas',
            },
          ],
        },
      ],
      panelistsPanel: [
        { name: 'Jess Lin', role: 'Recruiter', score: 4 },
        { name: 'Mina Park', role: 'Hiring manager', score: 3 },
        { name: 'Ravi Desai', role: 'Tech deep-dive', score: 4 },
        { name: 'Elena Vargas', role: 'Values', score: 3 },
      ],
      recommendation: 'Advance to offer',
      read: false,
    },
    d2: {
      candidateId: 'd2',
      candidateName: 'Jamie Wu',
      candidateAvatar: 'JW',
      candidateColor: '#D8EFE3',
      candidateStage: 'Panel complete',
      roleId: 'ios-sea',
      roleTitle: 'Senior iOS Eng',
      aggregateScore: 3.2,
      scoreScale: 4,
      overall: {
        summary:
          'Jamie is a craft-first engineer with excellent UIKit fundamentals and an under-indexed but solid product instinct. Slightly lighter on greenfield work than Noor.',
        strengths: [
          'UIKit and animation fidelity — the work samples are exceptional.',
          'Product instincts — catches UX bugs during implementation.',
        ],
        watchouts: [
          'Greenfield / 0-to-1 experience is thinner than the role suggests.',
          'Panel depth rounds were briefer than ideal.',
        ],
        nextSteps: [
          'Schedule a 30-min product deep-dive with the PM lead.',
          'Hold on decision until product deep-dive feedback is in.',
        ],
        verdict: 'mixed',
      },
      rounds: [
        {
          id: 'rs',
          title: 'Recruiter screen',
          interviewer: 'Jess Lin',
          date: '2026-04-06',
          score: 3,
          notes: 'Strong work samples; a little shy on motivations.',
          quotes: [
            {
              text: 'Portfolio quality spoke louder than the narrative.',
              type: 'strength',
              attribution: 'Jess Lin',
            },
          ],
        },
        {
          id: 'hm',
          title: 'Hiring manager',
          interviewer: 'Mina Park',
          date: '2026-04-09',
          score: 3,
          notes: 'Solid on scoping. Needs a little stretching on ambiguity.',
          quotes: [
            {
              text: 'Does great when the problem is stated. Wanted to see more pull on vague ones.',
              type: 'concern',
              attribution: 'Mina Park',
            },
          ],
        },
        {
          id: 'tech',
          title: 'Technical deep-dive',
          interviewer: 'Ravi Desai',
          date: '2026-04-11',
          score: 4,
          notes: 'Built out a table-view perf walk-through live with clean tradeoffs.',
          quotes: [
            {
              text: 'Perf walk-through was live code, not slides. Strong.',
              type: 'strength',
              attribution: 'Ravi Desai',
            },
          ],
        },
      ],
      panelistsPanel: [
        { name: 'Jess Lin', role: 'Recruiter', score: 3 },
        { name: 'Mina Park', role: 'Hiring manager', score: 3 },
        { name: 'Ravi Desai', role: 'Tech deep-dive', score: 4 },
      ],
      recommendation: 'Hold for product deep-dive',
      read: false,
    },
  },
  'des-ldn': {
    d1: {
      candidateId: 'd1',
      candidateName: 'Noor Haidari',
      candidateAvatar: 'NH',
      candidateColor: '#E9DFF5',
      candidateStage: 'Panel complete',
      roleId: 'des-ldn',
      roleTitle: 'Product Designer · London',
      aggregateScore: 3.4,
      scoreScale: 4,
      overall: {
        summary:
          'Noor brings crisp systems thinking and unusually strong motion chops for a product designer. Slightly lighter on end-to-end product judgement.',
        strengths: [
          'Design systems — maintained a token library at scale.',
          'Motion craft — genuine depth, not just Lottie-polish.',
          'Collaboration — recruited by two interviewers as a “please join my team” vote.',
        ],
        watchouts: [
          'Product judgement on tradeoffs — present but untested in a Staff context.',
          'London time-zone overlap with SF team — workable, not ideal.',
        ],
        nextSteps: [
          'Reference call with previous design lead.',
          'Discuss time-zone expectations with TLs before extending.',
        ],
        verdict: 'strong',
      },
      rounds: [
        {
          id: 'rs',
          title: 'Recruiter screen',
          interviewer: 'Sloane Aggarwal',
          date: '2026-04-03',
          score: 4,
          notes: 'Strong portfolio walk-through; articulate on craft and rationale.',
          quotes: [
            {
              text: 'She narrated each decision, not each screen. That is Staff-shape.',
              type: 'strength',
              attribution: 'Sloane Aggarwal',
            },
          ],
        },
        {
          id: 'hm',
          title: 'Hiring manager',
          interviewer: 'Joon Lee',
          date: '2026-04-07',
          score: 3,
          notes: 'Good on systems; needs more reps on tradeoff conversations.',
          quotes: [
            {
              text: 'Great on systems. I want one more probe on product tradeoffs.',
              type: 'concern',
              attribution: 'Joon Lee',
            },
          ],
        },
        {
          id: 'craft',
          title: 'Craft review',
          interviewer: 'Ilya Volkov',
          date: '2026-04-09',
          score: 4,
          notes: 'Motion work was standout. Genuine depth, not surface polish.',
          quotes: [
            {
              text: 'The motion work made me re-open the recruiter loop. That rarely happens.',
              type: 'strength',
              attribution: 'Ilya Volkov',
            },
          ],
        },
        {
          id: 'cv',
          title: 'Culture & values',
          interviewer: 'Sam Bennett',
          date: '2026-04-11',
          score: 3,
          notes: 'Warm, curious, low ego. No concerns.',
          quotes: [
            {
              text: 'Asked three questions of me I had not thought about in years. Low ego, high curiosity.',
              type: 'strength',
              attribution: 'Sam Bennett',
            },
          ],
        },
      ],
      panelistsPanel: [
        { name: 'Sloane Aggarwal', role: 'Recruiter', score: 4 },
        { name: 'Joon Lee', role: 'Hiring manager', score: 3 },
        { name: 'Ilya Volkov', role: 'Craft', score: 4 },
        { name: 'Sam Bennett', role: 'Values', score: 3 },
      ],
      recommendation: 'Advance to offer',
      read: false,
    },
  },
};

export function getPacket(roleId: string, candidateId: string): FeedbackPacket | null {
  return FEEDBACK_PACKETS[roleId]?.[candidateId] ?? null;
}

export function rolesWithPackets(): string[] {
  return Object.keys(FEEDBACK_PACKETS);
}

export function candidatesForRolePackets(roleId: string): string[] {
  return Object.keys(FEEDBACK_PACKETS[roleId] ?? {});
}
