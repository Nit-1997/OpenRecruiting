import type { RoundRating } from '@/domain';

/**
 * Per-interview "detailed scorecard" — richer than the per-question
 * FeedbackEntry: each evaluation criterion carries an at-a-glance summary
 * plus multiple evidence bundles that are individually tagged as
 * Supported, Contradicted, or Not Supported with quoted transcript
 * excerpts. Rendered in the packet drawer alongside the plain
 * EvidenceList when a candidate/round has one on file.
 */

export type DetailedEvidenceVerdict = 'supported' | 'contradicted' | 'not_supported';

export interface DetailedEvidenceBundle {
  heading: string;
  verdict: DetailedEvidenceVerdict;
  quotes: string[];
}

export interface DetailedScorecardCriterion {
  id: string;
  title: string;
  description: string;
  body: string;
  bundles: DetailedEvidenceBundle[];
}

export interface DetailedScorecard {
  candidateRoundId: string;
  roundLabel: string;
  verdict: RoundRating;
  verdictDate: string;
  summary: string;
  criteria: DetailedScorecardCriterion[];
}

/**
 * Keyed by candidate_round_id, which in the mock DB follows
 * `{reqId}_{candidateFixtureId}_{reqId}_round_{n}`. See
 * `buildCandidatesAndRounds` in src/services/seed.ts — the prefix
 * `pm-sfo_c17_pm-sfo_round_1` resolves to Amara Valeri's Round 1
 * (recruiter screen) on the Staff PM requisition.
 */
export const DETAILED_SCORECARDS: Record<string, DetailedScorecard> = {
  'pm-sfo_c17_pm-sfo_round_1': {
    candidateRoundId: 'pm-sfo_c17_pm-sfo_round_1',
    roundLabel: 'Round 1 · Resume Screen & Recruiter Call',
    verdict: 'strong_yes',
    verdictDate: '2026-04-22',
    summary:
      'Amara comes across as a strong hire for the Staff PM bar. She carries a clear, independently-owned scale-up story (health systems, 0→1 to 100K users in six months) that lines up tightly with the Staff-level ownership we need, and her mentorship track record on that same program — running APMs and orchestrating analytics, design, and user research — adds a coaching signal the team is actively asking for. The interviewer flagged executive-communication as skipped rather than covered, which is the one criterion we should intentionally pressure-test in the HM round before anchoring on the hire.',
    criteria: [
      {
        id: 'lifecycle_ownership',
        title: 'Product lifecycle ownership',
        description:
          'How independently the candidate has owned discovery, delivery, and iteration at the Staff level.',
        body: 'Amara gave a concrete, independently-owned 0-to-1 narrative at health-systems scale — moving a scrappy problem statement through phased rollout to 100K users in six months. The arc is specific enough to be verifiable and reads like Staff-level ownership rather than project-managed delivery. The only soft spot is that the story is carried by a single program; a follow-up should probe whether the ownership pattern repeats across domains.',
        bundles: [
          {
            heading: 'Independently ran a 0-to-1 scale-up at Staff-level ambiguity',
            verdict: 'supported',
            quotes: [
              '"took it from a scrappy open ended problem statement to all the way to the scale of 5,000 users, 10,000 users, and a 100,000 users in a span of six months" — candidate narrative on health-systems program',
              '"very impressive given the [ambiguity] they had in terms of problem definition. Well as actually running through the scale up of this phase rollout plan" — Robin, closing assessment',
              '"a certain sense of running things independently at scale in the past" — Robin, opening impression on lifecycle ownership',
            ],
          },
          {
            heading: 'Framed rollout as a phased, metric-anchored plan rather than a launch',
            verdict: 'supported',
            quotes: [
              '"5,000 users, 10,000 users, and a 100,000 users in a span of six months" — candidate described rollout as stepped user-growth milestones, not a single launch',
              '"actually running through the scale up of this phase rollout plan" — Robin explicitly flagged phased rollout as the strong signal, not just hitting scale',
            ],
          },
          {
            heading:
              'Breadth of ownership across multiple lifecycle stages is only single-program evidence',
            verdict: 'contradicted',
            quotes: [
              'Candidate anchored the entire lifecycle answer on one health-systems program; no second example surfaced when interviewer probed for a specific one.',
              '"The[y] told me about the project to scale health systems…" — only program cited across discovery, delivery, and iteration',
              'Staff-level bar typically expects two independent end-to-end examples; second case study should be pressure-tested in the HM round before locking in.',
            ],
          },
        ],
      },
      {
        id: 'exec_communication',
        title: 'Executive communication',
        description: 'How the candidate influences and aligns senior stakeholders under scrutiny.',
        body: 'Interviewer explicitly skipped this criterion during the recruiter screen, so there is no first-hand evidence either way. The lifecycle-ownership answer implies executive exposure (scaling to 100K users presumes VP-level reviews), but nothing was said on presence, written artifacts, or how Amara lands with senior stakeholders. Flag this as the priority probe for the hiring-manager round.',
        bundles: [
          {
            heading: 'Criterion was intentionally skipped during the screen',
            verdict: 'not_supported',
            quotes: [
              '"I wanna skip this." — Robin, when asked about executive-communication signal',
              'No direct transcript evidence of senior-stakeholder influence, written memo quality, or exec-review behavior in this round.',
            ],
          },
          {
            heading: 'Implied executive exposure from the scale-up narrative, but not validated',
            verdict: 'not_supported',
            quotes: [
              'The 100K-user scale-up program implies leadership-level reviews, but the interviewer did not probe how Amara showed up in those forums.',
              'Follow-up probe: ask HM round to pressure-test written artifacts (strategy memo, review deck) and a specific "lost the room, recovered it" moment.',
            ],
          },
        ],
      },
      {
        id: 'pm_mentorship',
        title: 'PM mentorship & multiplier',
        description:
          'Track record developing junior PMs and orchestrating cross-functional partners.',
        body: 'Strongest non-lifecycle signal in the screen. Amara oversaw APMs end-to-end on the same health-systems program and independently coordinated analytics, design, and user research — the profile we want for a Staff PM expected to compound the team. Mentorship is grounded in the same program, so the caveat on lifecycle breadth applies here too.',
        bundles: [
          {
            heading: 'Oversaw APMs end-to-end on a multi-quarter program',
            verdict: 'supported',
            quotes: [
              '"they actually worked with a product manager [and] associate product managers to get this to completion. So they oversaw the entire process" — Robin, on mentorship capability',
              'Mentorship ran for the full six-month rollout, not a one-off coaching moment.',
            ],
          },
          {
            heading:
              'Orchestrated analytics, design, and user research as a cross-functional leader',
            verdict: 'supported',
            quotes: [
              '"independently manage[d] the analytics and design folks. And collaborated very closely with the user research department." — Robin, cross-functional orchestration',
              'Signals a PM-multiplier profile rather than a lone-IC-PM pattern — matches the Staff PM mandate for this role.',
            ],
          },
          {
            heading: 'Mentorship evidence is scoped to the same program as the lifecycle story',
            verdict: 'contradicted',
            quotes: [
              '"a bunch of mentorship in the project that I\'ve already mentioned" — Robin explicitly anchored mentorship back to the health-systems program',
              'Ask in the HM round for a second mentorship example from a different org context (e.g., PM who did not report into her, or a cross-company mentoring relationship).',
            ],
          },
        ],
      },
      {
        id: 'overall_recommendation',
        title: 'Overall recommendation',
        description: "Interviewer's hire verdict and relative placement in the recent pipeline.",
        body: 'Robin lands on a strong hire, explicitly placing Amara in the top cohort of recent candidates. Given the strength on lifecycle ownership and mentorship plus no surfaced blockers, recommend advancing to the hiring-manager round with the executive-communication probe queued up as the priority gap-fill.',
        bundles: [
          {
            heading: 'Unambiguous hire verdict, top-of-recent-pipeline placement',
            verdict: 'supported',
            quotes: [
              '"I would lean on hiring this person. Definitely a strong hire." — Robin, closing verdict',
              '"will add value to the team. I think one of the better candidates we\'ve seen more recently." — Robin, relative ranking',
            ],
          },
          {
            heading: 'No concerns raised at screen-close',
            verdict: 'supported',
            quotes: [
              '"No. Nothing else." — Robin, when asked for any residual concerns before wrapping',
              'No tenure, comp, timing, or narrative red flags surfaced in the 3-minute debrief.',
            ],
          },
        ],
      },
    ],
  },
};

export function getDetailedScorecard(candidateRoundId: string): DetailedScorecard | null {
  return DETAILED_SCORECARDS[candidateRoundId] ?? null;
}
