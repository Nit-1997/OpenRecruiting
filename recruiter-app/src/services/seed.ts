import type {
  Candidate,
  CandidateRound,
  FeedbackEntry,
  Integration,
  Requisition,
  Round,
  RoundRecording,
  TranscriptSegment,
  UntrackedInterview,
} from '@/domain';
import { getCandidatesForReq } from '@/fixtures/candidates';
import { REQS, type RoleFixture } from '@/fixtures/roles';
import {
  UNTRACKED_INTERVIEWS,
  type UntrackedInterview as UntrackedFixture,
} from '@/fixtures/untracked-interviews';
import { isV2ApiEnabled } from '@/lib/env';
import { generateId, type MockDb, resetDb } from './mock-db';

const NOW = '2026-04-20T12:00:00Z';
const ORG_ID = 'org_1';

function mapStatus(legacy: RoleFixture['status']): Requisition['status'] {
  if (legacy === 'live') return 'planned';
  if (legacy === 'draft') return 'intake_pending';
  return 'closed';
}

function mapUntrackedStatus(s: UntrackedFixture['status']): UntrackedInterview['status'] {
  if (s === 'failed') return 'dismissed';
  return s;
}

const ROUND_QUESTIONS: Record<
  string,
  Array<{ heading: string; description: string }>
> = {
  screening: [
    {
      heading: 'Motivation & fit',
      description: 'Why this role, why now — red flags in narrative or timing.',
    },
    {
      heading: 'Role alignment',
      description: 'Match between background and the job-to-be-done at this level.',
    },
    {
      heading: 'Compensation expectations',
      description: 'Range fit, notice period, competing offers.',
    },
  ],
  behavioral: [
    {
      heading: 'Ownership & accountability',
      description: 'Signals of driving outcomes, taking heat, repair after failure.',
    },
    {
      heading: 'Prioritization under ambiguity',
      description: 'How they choose what not to do when priorities collide.',
    },
    {
      heading: 'Stakeholder influence',
      description: 'Evidence of moving senior/cross-functional partners without authority.',
    },
    {
      heading: 'Learning from mistakes',
      description: 'A specific, owned failure — not a success story in disguise.',
    },
  ],
  technical: [
    {
      heading: 'Depth of craft',
      description: 'Systems thinking, reads like a practitioner not a narrator.',
    },
    {
      heading: 'Tradeoff articulation',
      description: 'Explicit about cost/benefit, names what they would give up.',
    },
    {
      heading: 'Debugging & instincts',
      description: 'How they localize a novel failure; hypotheses over guesses.',
    },
  ],
  panel: [
    {
      heading: 'Product sense',
      description: 'Reframes the prompt, tests assumptions, proposes a crisp cut.',
    },
    {
      heading: 'Strategic thinking',
      description: 'Connects the problem to 3–5 year bets, not just next sprint.',
    },
    {
      heading: 'Communication & presence',
      description: 'Clear, direct, pushes back without heat. Listens.',
    },
  ],
  culture: [
    {
      heading: 'Collaboration & repair',
      description: 'How they handle conflict with an engineering or design peer.',
    },
    {
      heading: 'Values alignment',
      description: 'Specific examples that land on our operating principles.',
    },
    {
      heading: 'Low-ego learning',
      description: 'Evidence of updating beliefs after new information.',
    },
  ],
  final: [
    {
      heading: 'Closing signal',
      description: 'Where would they land in month 1? What will they push on?',
    },
    {
      heading: 'Risks and mitigations',
      description: 'What we need to watch for; what we offer to support.',
    },
  ],
};

function buildRoundsForRole(
  reqId: string,
  _title: string,
  mustHaveSkills: string[],
): Round[] {
  const template: Array<{ name: string; category: Round['category']; minutes: number }> = [
    { name: 'Resume screen + recruiter', category: 'screening', minutes: 30 },
    { name: 'Hiring manager interview', category: 'behavioral', minutes: 45 },
    { name: 'Product sense & strategy panel', category: 'panel', minutes: 60 },
    { name: 'Culture & values interview', category: 'culture', minutes: 45 },
  ];
  return template.map((t, i) => {
    const roundId = `${reqId}_round_${i + 1}`;
    const qs = ROUND_QUESTIONS[t.category] ?? [];
    const skillsPerRound = mustHaveSkills.length
      ? Array.from(
          { length: Math.min(3, mustHaveSkills.length) },
          (_, k) => mustHaveSkills[(i + k) % mustHaveSkills.length] as string,
        )
      : [];
    return {
      id: roundId,
      requisition_id: reqId,
      round_number: i + 1,
      name: t.name,
      category: t.category,
      duration_minutes: t.minutes,
      skills: skillsPerRound,
      guidelines: [],
      feedback_questions: qs.map((q, qi) => ({
        id: `${roundId}_q${qi + 1}`,
        round_id: roundId,
        question_number: qi + 1,
        heading: q.heading,
        description: q.description,
      })),
      created_at: NOW,
      updated_at: NOW,
    };
  });
}

function buildRequisitions(): Requisition[] {
  return REQS.map((r) => ({
    id: r.id,
    organization_id: ORG_ID,
    role_title: r.title,
    role_location: r.loc,
    department: r.dept,
    created_by: 'user_1',
    created_by_name: r.owner,
    experience_min_years: 5,
    experience_max_years: null,
    status: mapStatus(r.status),
    intake_notes: '',
    job_description: '',
    must_have_skills: r.must_have,
    good_to_have_skills: r.nice_to_have,
    rounds: buildRoundsForRole(r.id, r.title, r.must_have),
    created_at: r.created_at,
    updated_at: NOW,
  }));
}

/**
 * Per-candidate-round overrides applied during seed. Keyed by the round
 * id built in `buildCandidatesAndRounds` — `{reqId}_{fixtureId}_{roundId}`.
 * Use this for candidates whose round outcome must differ from the
 * generic "completed rounds get 'yes' + flag" default (e.g., a fully
 * detailed filled scorecard on file).
 */
const CANDIDATE_ROUND_OVERRIDES: Record<
  string,
  {
    rating?: CandidateRound['rating'];
    summary?: string;
    interviewer_email?: string;
    interviewer_name?: string;
  }
> = {
  'pm-sfo_c17_pm-sfo_round_1': {
    rating: 'strong_yes',
    summary:
      'Strong hire verdict. Clear independently-owned 0-to-1 scale-up (health systems, 100K users in six months) + PM mentorship signal. Exec-communication was skipped — probe in HM round before locking in.',
    interviewer_email: 'founder@example.com',
    interviewer_name: 'Rishit Chaturvedi',
  },
};

function buildCandidatesAndRounds(requisitions: Requisition[]): {
  candidates: Candidate[];
  candidate_rounds: CandidateRound[];
} {
  const candidates: Candidate[] = [];
  const candidate_rounds: CandidateRound[] = [];
  requisitions.forEach((req) => {
    const seeded = getCandidatesForReq(req.id);
    seeded.forEach((c) => {
      const uniqueId = `${req.id}_${c.id}`;
      const cand: Candidate = {
        id: uniqueId,
        requisition_id: req.id,
        name: c.name,
        email: `${c.name.toLowerCase().replace(/[^a-z]+/g, '.')}@example.com`,
        phone: null,
        resume_url: null,
        avatar_initials: c.avatar,
        avatar_color: c.color,
        status: c.scoresIn >= c.rounds ? 'hired' : 'active',
        final_verdict: c.scoresIn >= c.rounds ? 'hire' : null,
        current_round_id: req.rounds[Math.min(c.scoresIn, req.rounds.length - 1)]?.id ?? null,
        tags: [],
        source: 'referral',
        created_at: NOW,
        updated_at: NOW,
      };
      candidates.push(cand);
      req.rounds.forEach((round, i) => {
        const completed = i < c.scoresIn;
        const override = CANDIDATE_ROUND_OVERRIDES[`${uniqueId}_${round.id}`];
        const rating = completed ? (override?.rating ?? 'yes') : null;
        const interviewerName = completed
          ? (override?.interviewer_name ?? 'Jordan')
          : null;
        const interviewerEmail = completed
          ? (override?.interviewer_email ?? 'recruiter@example.com')
          : null;
        const candName = c.name;
        const questionSummaries: Record<string, string> = {};
        if (completed) {
          round.feedback_questions.forEach((q) => {
            questionSummaries[q.id] = synthesizeQuestionSummary(candName, q.heading, rating);
          });
        }
        // Approve most completed rounds; leave a few unapproved so the request-feedback
        // empty-state is also visible somewhere in the demo.
        const approved = completed && (uniqueId.charCodeAt(2) % 4 !== 0);
        const summaryText = completed
          ? (override?.summary ?? synthesizeRoundSummary(candName, round.name, rating))
          : '';
        const scheduledAt = completed
          ? NOW
          : i === c.scoresIn
            ? '2026-04-25T17:00:00Z'
            : null;
        candidate_rounds.push({
          id: `${uniqueId}_${round.id}`,
          candidate_id: uniqueId,
          round_id: round.id,
          status: completed ? 'completed' : i === c.scoresIn ? 'scheduled' : 'pending',
          scorecard_status: completed ? 'complete' : 'pending',
          rating,
          summary: summaryText,
          question_summaries: questionSummaries,
          authenticity_signals: null,
          feedback_approved_at: approved ? NOW : null,
          feedback_approved_by_email: approved ? interviewerEmail : null,
          scheduled_at: scheduledAt,
          scheduling_timezone: null,
          completed_at: completed ? NOW : null,
          interviewer_email: interviewerEmail,
          interviewer_name: interviewerName,
          meeting_url: null,
          scorecard: [],
        });
      });
    });
  });
  return { candidates, candidate_rounds };
}

function buildIntegrations(): Integration[] {
  return [
    {
      provider: 'slack',
      status: 'connected',
      label: 'Slack',
      blurb: 'Mirror feedback requests + reminders into a channel.',
      connected_at: NOW,
      last_synced_at: NOW,
      metadata: { workspace: 'OpenRecruiting HQ', channel: '#hiring' },
    },
    {
      provider: 'recall',
      status: 'connected',
      label: 'Recall.ai',
      blurb: 'Join interviews, capture transcripts + recordings.',
      connected_at: NOW,
      last_synced_at: NOW,
      metadata: { bot_email: 'scout-bot@recall.ai' },
    },
    {
      provider: 'untracked_bot',
      status: 'disabled',
      label: 'Untracked-interview bot',
      blurb: 'Auto-join calendar events not linked to a OpenRecruiting role.',
      connected_at: null,
      last_synced_at: null,
      metadata: {},
    },
  ];
}

function buildUntracked(): UntrackedInterview[] {
  return UNTRACKED_INTERVIEWS.map((u) => ({
    id: u.id,
    candidate_name: u.candidate_name,
    candidate_email: u.candidate_email,
    event_title: u.event_title,
    event_start: u.event_start,
    event_duration_minutes: 45,
    interviewer_email: u.interviewer_email,
    recording_url: null,
    status: mapUntrackedStatus(u.status),
    imported_candidate_id: null,
    imported_requisition_id: null,
    // Mock-path matches the v2 backend contract: each row carries the
    // synthetic (req, candidate) backing its captured candidate_round so
    // the FE can open the packet via the standard RPC.
    source_candidate_id: untrackedCandidateId(u.id),
    source_requisition_id: UNTRACKED_GENERIC_REQ_ID,
    detected_at: u.event_start,
  }));
}

// Mirrors backend `org_generic_template_bindings.materialized_requisition_id`
// (see backend/app/api/v2/services/untracked_service.py). One hidden
// requisition per org holds every captured untracked candidate + their
// recorded round, so the existing PacketDrawer can render an untracked
// interview's feedback packet with no special-case branch.
export const UNTRACKED_GENERIC_REQ_ID = 'req_ut_generic';
export const UNTRACKED_GENERIC_ROUND_ID = 'round_ut_generic';

export function untrackedCandidateId(utId: string): string {
  return `cand_ut_${utId}`;
}

export function untrackedCandidateRoundId(utId: string): string {
  return `cr_ut_${utId}`;
}

const UNTRACKED_GENERIC_QUESTIONS = [
  {
    heading: 'Role-related signal',
    description: 'What did the candidate demonstrate that maps to a hireable role?',
  },
  {
    heading: 'Depth of experience',
    description: 'Evidence of real, specific, owned outcomes — not narration.',
  },
  {
    heading: 'Communication & presence',
    description: 'Clarity, directness, and ability to land complex ideas concisely.',
  },
];

function buildUntrackedGenericRequisition(): Requisition {
  const reqId = UNTRACKED_GENERIC_REQ_ID;
  const roundId = UNTRACKED_GENERIC_ROUND_ID;
  const round: Round = {
    id: roundId,
    requisition_id: reqId,
    round_number: 1,
    name: 'Untracked interview',
    category: 'panel',
    duration_minutes: 45,
    description:
      'Calendar-detected interview captured by OpenRecruiting without a linked role. Re-process by linking to an existing role, or convert it into a new role.',
    skills: [],
    guidelines: [],
    feedback_questions: UNTRACKED_GENERIC_QUESTIONS.map((q, i) => ({
      id: `${roundId}_q${i + 1}`,
      round_id: roundId,
      question_number: i + 1,
      heading: q.heading,
      description: q.description,
    })),
    created_at: NOW,
    updated_at: NOW,
  };
  return {
    id: reqId,
    organization_id: ORG_ID,
    role_title: 'Untracked interview',
    role_location: '—',
    department: '—',
    created_by: 'system',
    created_by_name: 'OpenRecruiting',
    experience_min_years: 0,
    experience_max_years: null,
    status: 'closed',
    intake_notes: '',
    job_description: '',
    must_have_skills: [],
    good_to_have_skills: [],
    rounds: [round],
    created_at: NOW,
    updated_at: NOW,
  };
}

function buildUntrackedTranscript(candidateName: string): TranscriptSegment[] {
  const first = candidateName.split(' ')[0] ?? candidateName;
  return [
    {
      start_seconds: 0,
      end_seconds: 18,
      speaker: 'Interviewer',
      text: `Thanks for making time today. Want to start by walking me through the project you led most recently?`,
    },
    {
      start_seconds: 18,
      end_seconds: 92,
      speaker: first,
      text: `Sure. I led an end-to-end activation overhaul last quarter — we instrumented the funnel, shipped 4 experiments, and ended up with a 30% lift in week-one activation. I owned scoping, ran the readouts, and pushed back on a tempting metric we almost shipped against.`,
    },
    {
      start_seconds: 92,
      end_seconds: 110,
      speaker: 'Interviewer',
      text: `What was the hardest tradeoff in that work?`,
    },
    {
      start_seconds: 110,
      end_seconds: 184,
      speaker: first,
      text: `Speed versus blast radius. We had a working fix in week one but only a 40% confidence interval on the impact estimate. Shipping it would have prevented us from learning whether the deeper variant — which we eventually landed on — was actually better. I lost a week of velocity but kept the experiment clean.`,
    },
    {
      start_seconds: 184,
      end_seconds: 210,
      speaker: 'Interviewer',
      text: `How did your team react to that call?`,
    },
    {
      start_seconds: 210,
      end_seconds: 268,
      speaker: first,
      text: `Mixed at first. I wrote a one-pager arguing the tradeoff, talked through it with my PM and the staff engineer, and got buy-in. After it landed I think people internalized it as the right call.`,
    },
  ];
}

function buildUntrackedSynthetics(untracked: UntrackedInterview[]): {
  req: Requisition;
  candidates: Candidate[];
  rounds: CandidateRound[];
  feedback_entries: FeedbackEntry[];
  recordings: RoundRecording[];
} {
  const req = buildUntrackedGenericRequisition();
  const round = req.rounds[0];
  if (!round) throw new Error('untracked generic req must have a round');
  const candidates: Candidate[] = [];
  const rounds: CandidateRound[] = [];
  const feedback_entries: FeedbackEntry[] = [];
  const recordings: RoundRecording[] = [];

  untracked.forEach((u, idx) => {
    const candId = untrackedCandidateId(u.id);
    const crId = untrackedCandidateRoundId(u.id);
    const rating: CandidateRound['rating'] = idx % 2 === 0 ? 'yes' : 'maybe';

    candidates.push({
      id: candId,
      requisition_id: req.id,
      name: u.candidate_name,
      email: u.candidate_email,
      phone: null,
      resume_url: null,
      avatar_initials: u.candidate_name
        .split(/\s+/)
        .slice(0, 2)
        .map((p) => p[0]?.toUpperCase() ?? '')
        .join(''),
      avatar_color: '#EADFD4',
      status: 'active',
      final_verdict: null,
      current_round_id: round.id,
      tags: [],
      source: 'untracked_capture',
      created_at: u.detected_at,
      updated_at: u.detected_at,
    });

    const questionSummaries: Record<string, string> = {};
    round.feedback_questions.forEach((q) => {
      questionSummaries[String(q.question_number)] = synthesizeQuestionSummary(
        u.candidate_name,
        q.heading,
        rating,
      );
    });

    rounds.push({
      id: crId,
      candidate_id: candId,
      round_id: round.id,
      status: 'completed',
      scorecard_status: 'complete',
      rating,
      summary: synthesizeRoundSummary(u.candidate_name, round.name, rating),
      question_summaries: questionSummaries,
      authenticity_signals: null,
      feedback_approved_at: null,
      feedback_approved_by_email: null,
      scheduled_at: u.event_start,
      scheduling_timezone: null,
      completed_at: u.event_start,
      interviewer_email: u.interviewer_email,
      interviewer_name: u.interviewer_email.split('@')[0]?.replace(/\./g, ' ') ?? null,
      meeting_url: null,
      scorecard: [],
    });

    round.feedback_questions.forEach((q, qIdx) => {
      const seedNum = candId.charCodeAt(2) + qIdx;
      const variants = pickPointVariants(rating, seedNum);
      variants.forEach((status, pIdx) => {
        feedback_entries.push({
          id: `fb_${crId}_${q.id}_${pIdx}`,
          candidate_round_id: crId,
          feedback_question_id: q.id,
          feedback_text: synthesizePointText(u.candidate_name, q.heading, status, pIdx),
          evidence_status: status,
          evidence: synthesizeEvidence(q.heading, status, pIdx),
          source: 'bot',
          created_at: u.event_start,
        });
      });
    });

    const transcript = buildUntrackedTranscript(u.candidate_name);
    recordings.push({
      candidate_round_id: crId,
      recording_url: `https://example.com/recording/${crId}.mp4`,
      transcript_excerpt: transcript[1]?.text ?? '',
      transcript_segments: transcript,
      duration_seconds: 268,
      feedback_start_seconds: null,
      available: true,
    });
  });

  return { req, candidates, rounds, feedback_entries, recordings };
}

function buildFeedbackEntries(
  requisitions: Requisition[],
  candidates: Candidate[],
  candidate_rounds: CandidateRound[],
): FeedbackEntry[] {
  const entries: FeedbackEntry[] = [];
  const reqById = new Map(requisitions.map((r) => [r.id, r] as const));
  const candById = new Map(candidates.map((c) => [c.id, c] as const));

  candidate_rounds.forEach((cr) => {
    if (cr.status !== 'completed') return;
    const cand = candById.get(cr.candidate_id);
    if (!cand) return;
    const req = reqById.get(cand.requisition_id);
    if (!req) return;
    const round = req.rounds.find((r) => r.id === cr.round_id);
    if (!round) return;

    round.feedback_questions.forEach((q, qIdx) => {
      // Generate 3 feedback points per question with mixed evidence_status
      // so the per-question rollup chip ("3 supported · 1 contradicted") is meaningful.
      const seedNum = cand.id.charCodeAt(2) + qIdx;
      const variants = pickPointVariants(cr.rating, seedNum);

      variants.forEach((status, pIdx) => {
        entries.push({
          id: `fb_${cr.id}_${q.id}_${pIdx}`,
          candidate_round_id: cr.id,
          feedback_question_id: q.id,
          feedback_text: synthesizePointText(cand.name, q.heading, status, pIdx),
          evidence_status: status,
          evidence: synthesizeEvidence(q.heading, status, pIdx),
          source: 'bot',
          created_at: cr.completed_at ?? NOW,
        });
      });
    });
  });

  return entries;
}

function pickPointVariants(
  rating: CandidateRound['rating'],
  seedNum: number,
): FeedbackEntry['evidence_status'][] {
  // Higher rating → more supported, fewer contradicted. Always 3 points per question.
  if (rating === 'strong_yes') return ['verified', 'verified', 'verified'];
  if (rating === 'yes') {
    return seedNum % 2 === 0
      ? ['verified', 'verified', 'partial']
      : ['verified', 'verified', 'verified'];
  }
  if (rating === 'maybe') {
    return seedNum % 2 === 0
      ? ['verified', 'partial', 'partial']
      : ['verified', 'partial', 'contradicted'];
  }
  // no / strong_no
  return ['partial', 'contradicted', 'contradicted'];
}

function synthesizeRoundSummary(
  candName: string,
  roundName: string,
  rating: CandidateRound['rating'],
): string {
  const first = candName.split(' ')[0];
  const lower = roundName.toLowerCase();
  switch (rating) {
    case 'strong_yes':
      return `${first} was a clear standout in the ${lower}. Showed independent ownership across scoping, execution, and post-launch instrumentation, with concrete metrics tied to every claim. Communicated tradeoffs cleanly and stayed crisp under follow-up. Recommend moving fast.`;
    case 'yes':
      return `${first} cleared the bar comfortably in the ${lower}. Demonstrated solid end-to-end ownership and walked through real examples without prompting. Some answers leaned rehearsed; would want to probe deeper on cross-functional conflict in the next round, but no blockers here.`;
    case 'maybe':
      return `${first} was on-bar but inconsistent in the ${lower}. Strong on framework and structure, weaker on specifics — needed two follow-ups on most metrics questions. Could be a hire if the next round confirms depth, but not a clear yes.`;
    case 'no':
      return `${first} did not clear the bar in the ${lower}. Examples felt high-level and self-assessment did not match the depth of execution they described. Recommend not advancing without strong reference signal.`;
    case 'strong_no':
      return `${first} was well below bar in the ${lower}. Multiple claims contradicted themselves under follow-up, and the candidate could not produce concrete numbers or outcomes. Strong recommendation against moving forward.`;
    default:
      return `${first} completed the ${lower}. Feedback pending interviewer confirmation.`;
  }
}

function synthesizeQuestionSummary(
  candName: string,
  heading: string,
  rating: CandidateRound['rating'],
): string {
  const verdict =
    rating === 'strong_yes'
      ? 'Strongly demonstrated'
      : rating === 'yes'
        ? 'Clearly demonstrated'
        : rating === 'maybe'
          ? 'Partially demonstrated, mixed signals'
          : 'Did not meet the bar';
  return `${verdict} on "${heading.toLowerCase()}". ${candName.split(' ')[0]} backed answers with concrete examples; interviewer probed twice and the answers held up.`;
}

function synthesizePointText(
  candName: string,
  heading: string,
  status: FeedbackEntry['evidence_status'],
  pointIdx: number,
): string {
  const first = candName.split(' ')[0];
  const claims = {
    supported: [
      `Strong answer on "${heading}". Walked through a concrete example end-to-end without prompting.`,
      `${first} cited measurable outcomes — "30% lift in activation" — when probed on this dimension.`,
      `Demonstrated structured thinking; broke the problem into 3 explicit tradeoffs and committed to one.`,
    ],
    verified: [
      `Strong answer on "${heading}". Walked through a concrete example end-to-end without prompting.`,
      `${first} cited measurable outcomes — "30% lift in activation" — when probed on this dimension.`,
      `Demonstrated structured thinking; broke the problem into 3 explicit tradeoffs and committed to one.`,
    ],
    partial: [
      `Answer was directionally right but lacked specifics. Needed two follow-ups to surface real numbers.`,
      `Framework was sound but example felt rehearsed; couldn't go beyond the canned story.`,
      `Got to the right conclusion but skipped the reasoning — would want to see independent depth in a follow-up.`,
    ],
    contradicted: [
      `Self-assessment did not match the example given. Story contradicted itself on ownership and outcome.`,
      `Claimed end-to-end ownership early, then admitted manager drove execution 12 minutes later.`,
      `Numbers cited didn't pass a sanity check against the timeline they described.`,
    ],
    none: [
      `Did not get to this in the time available — interviewer ran out of time before this question.`,
    ],
  } as const;
  const list = claims[status];
  return list[pointIdx % list.length] ?? list[0];
}

function synthesizeEvidence(
  heading: string,
  status: FeedbackEntry['evidence_status'],
  pointIdx: number,
): string[] {
  if (status === 'none') return [];
  const pool = {
    supported: [
      `"I led that effort end-to-end — I owned the rollout from week one." — on ${heading.toLowerCase()}`,
      `"We saw a 30% lift in activation in the first month after the change." — concrete metric`,
      `"Three tradeoffs: speed, observability, blast radius. We chose observability first." — structured framing`,
    ],
    verified: [
      `"I led that effort end-to-end — I owned the rollout from week one." — on ${heading.toLowerCase()}`,
      `"We saw a 30% lift in activation in the first month after the change." — concrete metric`,
      `"Three tradeoffs: speed, observability, blast radius. We chose observability first." — structured framing`,
    ],
    partial: [
      `"It worked out well overall." — vague, no specifics offered until probed`,
      `"We had a really good outcome." — couldn't quantify when asked`,
    ],
    contradicted: [
      `"I led the rollout end-to-end." — claim early in the round`,
      `"Actually my manager drove most of the execution; I supported." — said 12 minutes later`,
    ],
    none: [],
  } as const;
  const list: readonly string[] = pool[status];
  if (list.length === 0) return [];
  // Vary the slice per point so different points show different evidence.
  return [list[pointIdx % list.length] ?? (list[0] as string)];
}

export function buildSeed(): MockDb {
  const realReqs = buildRequisitions();
  const { candidates, candidate_rounds } = buildCandidatesAndRounds(realReqs);
  const feedback_entries = buildFeedbackEntries(realReqs, candidates, candidate_rounds);
  const untracked = buildUntracked();
  const utSynth = buildUntrackedSynthetics(untracked);
  // The generic untracked requisition holds candidate_rounds backing the
  // feedback packet for each detected interview. It's filtered out of the
  // public role list / candidates list by id prefix (`req_ut_*`) — see
  // services/requisitions.ts and services/candidates.ts.
  const requisitions = [...realReqs, utSynth.req];
  return {
    requisitions,
    candidates: [...candidates, ...utSynth.candidates],
    candidate_rounds: [...candidate_rounds, ...utSynth.rounds],
    feedback_entries: [...feedback_entries, ...utSynth.feedback_entries],
    recordings: [...utSynth.recordings],
    team_members: [
      {
        id: 'tm_1',
        user_id: 'user_1',
        name: 'Nitin',
        email: 'founder@example.com',
        role: 'owner',
        avatar_initials: 'N',
        avatar_color: '#EEE8DD',
        joined_at: NOW,
        last_active_at: NOW,
      },
    ],
    invites: [],
    billing: {
      plan_name: 'growth',
      plan_display_name: 'Growth',
      subscription_status: 'active',
      period_start: '2026-04-20T00:00:00Z',
      period_end: '2026-05-20T00:00:00Z',
      cancel_at_period_end: false,
      intake_total: 25,
      intake_used: 4,
      intake_topup: 0,
      interview_total: 250,
      interview_used: 68,
      interview_topup: 0,
    },
    integrations: buildIntegrations(),
    profile: {
      id: 'prof_1',
      user_id: 'user_1',
      name: 'Nitin',
      email: 'founder@example.com',
      avatar_initials: 'N',
      avatar_color: '#EEE8DD',
      timezone: 'America/Los_Angeles',
      onboarding_completed: true,
    },
    notification_prefs: {
      user_id: 'user_1',
      email_feedback_requests: true,
      email_interview_reminders: true,
      email_weekly_digest: true,
      slack_feedback_requests: true,
      slack_interview_reminders: false,
      slack_weekly_digest: false,
    },
    activity: [
      {
        id: generateId('act'),
        type: 'role:created',
        title: 'New role created',
        description: `${realReqs[0]?.role_title ?? 'Role'} was opened.`,
        actor_name: 'Nitin',
        requisition_id: realReqs[0]?.id ?? null,
        candidate_id: null,
        created_at: NOW,
      },
    ],
    untracked,
    _meta: { seeded_at: NOW, version: 1 },
  };
}

export function seedDb(): MockDb {
  const seed = buildSeed();
  resetDb(seed);
  return seed;
}

/**
 * Register the seed factory on `globalThis.__SEED` so `mock-db.getDb()`
 * can lazy-seed in the browser. This is the OPT-OUT test/demo path ONLY.
 *
 * CRITICAL data-integrity guard (FE-F5): when `isV2ApiEnabled()` is true
 * (the production default), this is a NO-OP — the seed factory is never
 * registered. If it were, any service method that still reads `getDb()` would
 * silently fabricate localStorage data indistinguishable from real backend
 * data. Gating registration here means a missed mock-only branch surfaces as
 * an empty/error state rather than fake data.
 *
 * @returns `true` if the factory was registered (mock mode), `false` if
 * skipped (v2 mode). The boolean is purely for test assertions.
 */
export function registerSeedFactory(): boolean {
  if (typeof globalThis === 'undefined') return false;
  if (isV2ApiEnabled()) return false;
  (globalThis as { __SEED?: typeof buildSeed }).__SEED = buildSeed;
  return true;
}
