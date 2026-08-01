// The dashboard plan tab speaks the `@/domain` Round (snake_case), but the
// Task-14 `ScreeningConfigPanel` is the intake-side component and takes a
// `@/types` Round (camelCase). Rather than fork the panel into a second
// implementation, we map the dashboard round into the camelCase shape the panel
// expects. The panel only reads `roundNumber` + `name` from the round prop, but
// we fill the full required shape so the contract is honest and type-safe.

import type { Round as DomainRound } from '@/domain';
import type {
  IntakeScreeningQuestion,
  RoundCategory,
  FeedbackQuestion as TypesFeedbackQuestion,
  Round as TypesRound,
} from '@/types';

// `@/domain` RoundCategory is free-text VARCHAR; `@/types` RoundCategory is a
// narrower union. The panel never branches on category, so we cast at this
// single, documented boundary rather than threaten the panel's other callers.
function toPanelCategory(category: string): RoundCategory {
  return category as RoundCategory;
}

function toPanelQuestion(q: DomainRound['feedback_questions'][number]): TypesFeedbackQuestion {
  return {
    id: q.id,
    roundId: q.round_id,
    questionNumber: q.question_number,
    heading: q.heading,
    description: q.description,
  };
}

function toPanelScreeningQuestion(
  q: NonNullable<DomainRound['screening_agent_questions']>[number],
): IntakeScreeningQuestion {
  return {
    id: q.id,
    order: q.order,
    dimension: q.dimension,
    question: q.question,
    probe: q.probe,
    durationMinutes: q.duration_minutes,
    signal: q.signal,
  };
}

export function toPanelRound(round: DomainRound): TypesRound {
  const out: TypesRound = {
    id: round.id,
    requisitionId: round.requisition_id,
    roundNumber: round.round_number,
    name: round.name,
    category: toPanelCategory(round.category),
    durationMinutes: round.duration_minutes,
    description: round.description ?? '',
    skills: round.skills,
    guidelines: round.guidelines,
    feedbackQuestions: round.feedback_questions.map(toPanelQuestion),
  };
  if (round.screening_agent_enabled !== undefined) {
    out.screeningAgentEnabled = round.screening_agent_enabled;
  }
  if (round.screening_agent_voice !== undefined) {
    out.screeningAgentVoice = round.screening_agent_voice;
  }
  if (round.screening_agent_questions !== undefined) {
    out.screeningAgentQuestions = round.screening_agent_questions.map(toPanelScreeningQuestion);
  }
  if (round.aiScreenable !== undefined) out.aiScreenable = round.aiScreenable;
  if (round.aiScreenableReason !== undefined) {
    out.aiScreenableReason = round.aiScreenableReason;
  }
  return out;
}
