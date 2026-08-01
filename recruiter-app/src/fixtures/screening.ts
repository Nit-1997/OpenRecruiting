import type { ScreeningAgentQuestion } from '@/domain';

export const SCREENING_AGENT_VOICE = 'Aura · "Luna"';
export const SCREENING_AGENT_FOLLOWUP = 'Adaptive probes';
export const SCREENING_AGENT_DEPLOY = 'All resume-passed';

export const DEFAULT_SCREENING_QUESTIONS: ScreeningAgentQuestion[] = [
  {
    id: 'sq_metric',
    order: 0,
    dimension: 'Metric Ownership',
    question:
      'Walk me through the last metric you owned end to end. What was the baseline, what did you move it to, and what would you have done differently in the first 30 days?',
    probe: 'Attribution — was the lift causal or correlated?',
    duration_minutes: 5,
    signal: 'Execution',
  },
  {
    id: 'sq_plg',
    order: 1,
    dimension: 'PLG Motion',
    question:
      "A free user just hit their 3rd session but hasn't converted. Walk me through how you'd design the next touch: product surface, trigger, message, and how you'd measure it.",
    probe: "What's your leading indicator vs. lagging indicator?",
    duration_minutes: 5,
    signal: 'PLG fluency',
  },
  {
    id: 'sq_judgment',
    order: 2,
    dimension: 'Judgment Under Ambiguity',
    question:
      'You have three bets on the roadmap: one has 70% confidence and modest upside, one has 20% confidence but could 3x the funnel, one unblocks the sales team. You can only ship one this quarter. Which, and why?',
    probe: 'How do you factor in org politics vs. expected value?',
    duration_minutes: 5,
    signal: 'Prioritization',
  },
  {
    id: 'sq_motivation',
    order: 3,
    dimension: 'Motivation',
    question:
      "Why now? What's pulling you out of your current role, and what does this role need to look like one year in for you to call it a win?",
    probe: 'Is this a push or a pull? Flag if push dominant.',
    duration_minutes: 3,
    signal: 'Retention risk',
  },
];

export function cloneDefaultScreeningQuestions(): ScreeningAgentQuestion[] {
  return DEFAULT_SCREENING_QUESTIONS.map((q) => ({ ...q }));
}
